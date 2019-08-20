import requests
import json
import bs4
import m3u8
import threading
import time
import os

class nico2py():

    def __init__( self ):

        #スレッド情報
        self.started   = threading.Event()
        self.threadDmc = threading.Thread()
        self.threadSml = threading.Thread()
        self.isDownload = False

    def getVideo( self, smUrl ):

        #キャッシュ初期化
        os.remove( "data.mp4" )
        
        #動画ページのhtmlを取得
        resSm = requests.post( smUrl )
        cookies = resSm.cookies.get_dict()

        #パースしてapi情報を取得
        soup = bs4.BeautifulSoup( resSm.content, "html.parser" )
        js_i_w_data = soup.find_all( id = "js-initial-watch-data" )

        #data-api-dataを取得
        api_data = json.loads( js_i_w_data[0].get("data-api-data") )
        self.__dumpJson( "dl_datas/data-api-data.json", api_data )

        self.threadDmc = threading.Thread( target=self.__sessionDmc )
        self.threadSml = threading.Thread( target=self.__sessionSmile, args=( api_data, cookies ) )

        #smileサーバー(旧方式)かdmcサーバー(新方式)を選択
        if api_data["video"]["dmcInfo"] == None:
            print("smile")
            self.threadSml.start()
        else:
            print("dmc")
            self.threadDmc.start()
        
        #読み込む分が生成される待ち時間
        time.sleep( 3 )

        return "data.mp4"
            
    def __sessionDmc( self ):
        
        fp = open( "dl_datas/data-api-data.json","r" )
        api_data = json.load(fp)
        fp.close()

        #session雛形を読み込み
        fp = open("session_proto.json","r")
        session_proto = json.load(fp)
        fp.close()

        #session-api
        self.__dumpJson( "dl_datas/session_api.json", api_data["video"]["dmcInfo"]["session_api"] )
        session_api = self.__loadJson( "dl_datas/session_api.json" )

        #リクエスト作成
        sessionReq = self.__setSession( session_proto, session_api )

        #リクエスト送信
        req = requests.Session()

        #dmcアドレスを設定
        dmc_adress = session_api["urls"][0]["url"] + "?_format=json"

        session_res:requests.Response = req.post( dmc_adress, json=sessionReq )

        dmc_session_res = json.loads(session_res.content)
        self.__dumpJson( "dl_datas/dmcSessionRes.json", dmc_session_res )

        if session_res.status_code != 201:
            print( session_res.text )
            exit()

        #masterm3u8取得
        rtsAddres = dmc_session_res["data"]["session"]["content_uri"]
        streamData = requests.get(rtsAddres)
        fp = open("dl_datas/master_list.m3u8","w")
        fp.write(streamData.text)
        fp.close()

        #playlist用urlを整形
        split_data = self.__splitUrl( rtsAddres )

        fp = open("dl_datas/master_list.m3u8","r")
        pl_data = fp.read().split("\n")
        pl_data.remove("")
        pl_data.reverse()
        fp.close()

        url = ""

        for i in range( len(split_data) - 1 ):
            if i == 0:
                url += split_data[i] + "//"
            else:
                url += split_data[i] + "/"
        
        url += pl_data[0]

        #playlistsを取得
        resPlayList = requests.get(url)
        fp = open( "dl_datas/playLists.m3u8", "w" )
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
        
        fp = open("data.mp4","wb+")

        self.isDownload = True

        for tsUrl in tsDatas.segments:

            print(str(tsUrl.uri))
            fp.write( requests.get(tsUrl.uri).content )

            if self.isDownload == False:
                break

        nico2py.isDownload = False
        fp.close()

    def __sessionSmile( self, api_data, cookie ):
        
        fp = open("data.mp4","wb+")

        #Smileサーバー設定
        smileUrl = api_data["video"]["smileInfo"]["url"]         
        
        #取得データサイズ設定
        rhead = dict()
        addSize = 100000
        rhead["Range"] = "bytes=0-10"
   
        #1回目データ取得
        fp = open("data.mp4","wb+")
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
        fp = open( file, "w" )
        json.dump( jdata, fp, indent=4 )
        fp.close()

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
        self.started.set()
        
        if self.threadSml.isAlive == True:
            self.threadSml.join()

        if self.threadDmc.isAlive == True:
            self.threadDmc.join()
