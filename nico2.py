import json
import os
import sys
import threading
import time

import bs4
import m3u8
import requests


class nico2py():

    def __init__( self ):

        #スレッド情報
        self.__started   = threading.Event()
        self.__threadDmc = threading.Thread()
        self.__threadSml = threading.Thread()
        self.__smUrl = str()
        self.isDownload = False
        self.isDump = False

    def getInfo( self, smUrl ):

        self.__smUrl = smUrl

        #動画ページのhtmlを取得
        resSm = requests.post( smUrl )

        #パースしてapi情報を取得
        soup = bs4.BeautifulSoup( resSm.content, "html.parser" )
        js_i_w_data = soup.find_all( id = "js-initial-watch-data" )

        #data-api-dataを取得
        api_data = json.loads( js_i_w_data[0].get("data-api-data") )

        #データ取得
        return { "title":api_data["video"]["title"], "url":smUrl, "thum":api_data["video"]["thumbnailURL"] } 

    def getVideo( self, smUrl ):

        self.__smUrl = smUrl   

        #キャッシュ初期化
        if os.path.exists( "contents/cache.mp4" ):
            os.remove( "contents/cache.mp4" )
        
        #動画ページのhtmlを取得
        resSm = requests.post( smUrl )
        cookies = resSm.cookies.get_dict()

        #パースしてapi情報を取得
        soup = bs4.BeautifulSoup( resSm.content, "html.parser" )
        js_i_w_data = soup.find_all( id = "js-initial-watch-data" )

        #data-api-dataを取得
        api_data = json.loads( js_i_w_data[0].get("data-api-data") )
        self.__dumpJson( "contents/data-api-data.json", api_data )

        self.__threadDmc = threading.Thread( target=self.__sessionDmc, args=( api_data, 0 ) )
        self.__threadSml = threading.Thread( target=self.__sessionSmile, args=( api_data, cookies ) )

        #smileサーバー(旧方式)かdmcサーバー(新方式)を選択
        if api_data["video"]["dmcInfo"] == None:
            print("smile")
            self.__threadSml.start()
        else:
            print("dmc")
            self.__threadDmc.start()
        
        #読み込む分が生成される待ち時間
        time.sleep( 3 )

        return "contents/cache.mp4"
            
    def __sessionDmc( self, api_data, dummy ):
        
        #session雛形を読み込み
        with open("contents/session_proto.json","r") as fp:
            session_proto = json.load(fp)

        #session-api
        self.__dumpJson( "contents/session_api.json", api_data["video"]["dmcInfo"]["session_api"] )
        session_api = api_data["video"]["dmcInfo"]["session_api"]

        #リクエスト作成
        sessionReq = self.__setSession( session_proto, session_api )
        req = requests.Session()

        #dmcアドレスを設定
        dmc_adress = session_api["urls"][0]["url"] + "?_format=json"
        session_res:requests.Response = req.post( dmc_adress, json=sessionReq )

        dmc_session_res = json.loads(session_res.content)
        self.__dumpJson( "contents/dmcSessionRes.json", dmc_session_res )

        if session_res.status_code != 201:
            print( session_res.text )
            return

        #masterm3u8取得
        rtsAddres = dmc_session_res["data"]["session"]["content_uri"]
        streamData = requests.get(rtsAddres)

        with open("contents/master_list.m3u8","w") as fp:
            fp.write(streamData.text)

        #playlist用urlを整形
        split_data = self.__splitUrl( rtsAddres )

        with open("contents/master_list.m3u8","r") as fp:
            pl_data = fp.read().split("\n")
            pl_data.remove("")
            pl_data.reverse()

        url = ""

        for i in range( len(split_data) - 1 ):
            if i == 0:
                url += split_data[i] + "//"
            else:
                url += split_data[i] + "/"
        
        url += pl_data[0]

        #playlistsを取得
        resPlayList = requests.get(url)
        if self.isDump:
            with open( "contents/playLists.m3u8", "w" ) as fp:
                fp.write(resPlayList.text)
        
        #tsを取得
        basePath = ""
        for i in range( len(split_data) - 1 ):
            if i == 0:
                basePath += split_data[i] + "//"
            else:
                basePath += split_data[i] + "/"


        tsDatas = m3u8.loads(resPlayList.text)
        tsDatas.base_path = basePath + "1/ts"
        
        self.isDownload = True
        heatBeat = time.time()

        params = dict()
        params["_format"] = "json"
        params["_method"] = "PUT"

        headers = dict()
        headers["Access-Control-Request-Headers"] = "content-type"
        headers["Access-Control-Request-Method"] = "POST"
        headers["Origin"] = "https://www.nicovideo.jp"
        headers["Referer"] = self.__smUrl
        headers["Sec-Fetch-Mode"] = "no-cors"

        hb_adress = "{0}/{1}".format( session_api["urls"][0]["url"], dmc_session_res["data"]["session"]["id"] )
        res :requests.Response= requests.options( hb_adress, headers=headers,params=params )
        print(res)
        print(res.request.headers)
        print(res.headers)

        headers = dict()
        headers["Accept"] = "aplication/json"
        headers["Content-Type"] = "aplication/json"
        headers["Origin"] = "https://www.nicovideo.jp"
        headers["Referer"] = self.__smUrl
        headers["Sec-Fetch-Mode"] = "cors"
        
        with open("contents/cache.mp4","wb+") as fp:

            i = 0
            for tsUrl in tsDatas.segments:

                i += 1
                res = requests.get( tsUrl.uri )
                print( "{0} / {1} : {2} bytes lifetime : {3}".format( i, len(tsDatas.segments), sys.getsizeof(res), (time.time() - heatBeat ) ) )
                fp.write( res.content )

                # heartbeat
                if (time.time() - heatBeat) >= 110:
                    session_res:requests.Response = requests.post( hb_adress, json=dmc_session_res["data"], headers=headers, params=params )
                    heatBeat = time.time()

                if self.isDownload == False:
                    break
                    
        nico2py.isDownload = False

    def __sessionSmile( self, api_data, cookie ):
        
        #Smileサーバー設定
        smileUrl = api_data["video"]["smileInfo"]["url"]         
        
        #取得データサイズ設定
        rhead = dict()
        addSize = 100000
        rhead["Range"] = "bytes=0-10"
        rhead["options"] = "post"
        
        #1回目データ取得
        fp = open("contents/cache.mp4","wb+")
        res:requests.Response = requests.get( smileUrl, headers=rhead, cookies=cookie )

        #全体サイズ取得
        length = int(res.headers["Content-Range"].split("/")[1])

        self.isDownload = True

        #全取得までは繰り返し
        for size in range( 0, length, addSize ):

            rhead["Range"] = "bytes={0}-{1}".format( size, size + addSize -1 )
            fp.write( requests.get( smileUrl,  headers=rhead, cookies=cookie ).content )
            print( "{0} / {1} : {2:.0%}".format( size + addSize -1, length, (size + addSize -1)/length ) )

            if self.isDownload == False:
                break
    
        self.isDownload = False
        fp.close()

    def __dumpJson( self, file, jdata ):

        if self.isDump:
            with open( file, "w" ) as fp:
                json.dump( jdata, fp, indent=4 )

    def __loadJson( self, file ):
        fp = open( file, "r" )
        ret = json.load(fp)
        fp.close()
        return ret

    def __setSession( self, proto, data ):

        proto["session"]["recipe_id"] = data["recipe_id"]
        proto["session"]["content_id"] = data["content_id"]
        proto["session"]["content_type"] = "movie"
        proto["session"]["content_src_id_sets"][0]["content_src_ids"][0]["src_id_to_mux"]["video_src_ids"][0] = data["videos"][0]
        proto["session"]["content_src_id_sets"][0]["content_src_ids"][0]["src_id_to_mux"]["audio_src_ids"][0] = data["audios"][0]
        proto["session"]["timing_constraint"] = "unlimited"
        proto["session"]["keep_method"]["heartbeat"]["lifetime"] = data["heartbeat_lifetime"]
        proto["session"]["protocol"]["name"] = "http"

        if data["urls"][0]["is_well_known_port"]:
            proto["session"]["protocol"]["parameters"]["http_parameters"]["parameters"]["hls_parameters"]["use_well_known_port"] = "yes"
        else:
            proto["session"]["protocol"]["parameters"]["http_parameters"]["parameters"]["hls_parameters"]["use_well_known_port"] = "no"

        if data["urls"][0]["is_ssl"]:
            proto["session"]["protocol"]["parameters"]["http_parameters"]["parameters"]["hls_parameters"]["use_ssl"] = "yes"
        else:
            proto["session"]["protocol"]["parameters"]["http_parameters"]["parameters"]["hls_parameters"]["use_ssl"] = "no"
        
        proto["session"]["content_uri"] = ""
        proto["session"]["session_operation_auth"]["session_operation_auth_by_signature"]["token"] = data["token"]
        proto["session"]["session_operation_auth"]["session_operation_auth_by_signature"]["signature"] = data["signature"]
        proto["session"]["content_auth"]["auth_type"] = data["auth_types"]["http"]
        proto["session"]["content_auth"]["content_key_timeout"] = data["content_key_timeout"]
        proto["session"]["content_auth"]["service_id"] = "nicovideo"
        proto["session"]["content_auth"]["service_user_id"] = data["service_user_id"]
        proto["session"]["client_info"]["player_id"] = data["player_id"]
        proto["session"]["priority"] = 0
        return proto

    def __splitUrl( self, url:str ):
        urls = url.split("//")
        ret = list()
        ret.append(urls[0])
        
        for s in urls[1].split("/"):
            ret.append(s)

        return ret

    def __del__( self ):

        #ダウンロードスレッドを終了
        self.__started.set()
        
        if self.__threadSml.isAlive == True:
            self.__threadSml.join()

        if self.__threadDmc.isAlive == True:
            self.__threadDmc.join()