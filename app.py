import os
import tornado.httpserver
import tornado.ioloop
import tornado.web
from creds import *
from requests import Request
import requests
import json
import re
import tempfile
import redis
import uuid
from pydub import AudioSegment
import speech_recognition as sr
from pymessenger.bot import Bot


TOKEN = "EAAJPHXpVWQIBAMXZC5aDFfQuCUUQfHIm65ccxiN39ymIz7haOVIpxFVqWsP5QviRZAc4xMdCvReTl2nzSikctr9ZAskZAABxzNpWZCCAeosR1mmsbqZBkpoZAbQNj9qdwD3PbxGowNNvGrTmqZBqFH5i6uSCF6aSDc0kaU1rM6RZCDAZDZD"
bot = Bot(TOKEN)
    
def gettoken(uid):
    red = redis.from_url(redis_url)
    token = red.get(uid+"-access_token")
    refresh = red.get(uid+"-refresh_token")
    if token:
        return token
    elif refresh:
        payload = {"client_id" : Client_ID, "client_secret" : Client_Secret, "refresh_token" : refresh, "grant_type" : "refresh_token", }
        url = "https://api.amazon.com/auth/o2/token"
        r = requests.post(url, data = payload)
        resp = json.loads(r.text)
        red.set(uid+"-access_token", resp['access_token'])
        red.expire(uid+"-access_token", 3600)
        return resp['access_token']
    else:
        return False
    
class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        return self.get_cookie("user")


class MainHandler(BaseHandler):
    @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        f = open('static/index.html', 'r')
        resp = f.read()
        f.close()
        self.write(resp)
        self.finish()


class StartAuthHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        scope="alexa_all"
        sd = json.dumps({
            "alexa:all": {
                "productID": "jacobsalexatest",
                "productInstanceAttributes": {
                    "deviceSerialNumber": "1"
                }
            }
        })
        url = "https://www.amazon.com/ap/oa"
        path = "https" + "://" + self.request.host 
        print("boo")
        callback = path + "/code"
        payload = {"client_id" : Client_ID, "scope" : "alexa:all", "scope_data" : sd, "response_type" : "code", "redirect_uri" : callback }
        req = Request('GET', url, params=payload)
        p = req.prepare()
        self.redirect(p.url)


class CodeAuthHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        code=self.get_argument("code")
        path = "https" + "://" + self.request.host 
        callback = path+"/code"
        payload = {"client_id" : Client_ID, "client_secret" : Client_Secret, "code" : code, "grant_type" : "authorization_code", "redirect_uri" : callback }
        url = "https://api.amazon.com/auth/o2/token"
        r = requests.post(url, data = payload)
        uid = str(uuid.uuid4())
        red = redis.from_url(redis_url)
        resp = json.loads(r.text)
        red.set(uid+"-access_token", resp['access_token'])
        red.expire(uid+"-access_token", 3600)
        red.set(uid+"-refresh_token", resp['refresh_token'])
        self.set_cookie("user", uid)
        self.redirect("/")                  

class LogoutHandler(BaseHandler):
    @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        uid = tornado.escape.xhtml_escape(self.current_user)
        red = redis.from_url(redis_url)
        red.delete(uid+"-access_token")
        red.delete(uid+"-refresh_token")
        self.clear_cookie("user")
        self.set_header('Content-Type', 'text/plain')
        self.write("Logged Out, Goodbye")
        self.finish()

class MessageHandler(BaseHandler):
    @tornado.web.asynchronous
    def get(self):
        print("here")
        if (self.get_argument("hub.verify_token", default=None, strip=False) == "my_voice_is_my_password_verify_me"):
            print("yes")
            self.set_header('Content-Type', 'text/plain')
            self.write(self.get_argument("hub.challenge", default=None, strip=False))
            self.finish()

    def post(self):
        output = tornado.escape.json_decode(self.request.body) 
        print("OUTPUT: ",output)
        event = output['entry'][0]['messaging']
        for x in event:
            if (x.get('message') and x['message'].get('text')):
                message = x['message']['text']
                recipient_id = x['sender']['id']


                print("Getting Alexa's response from AudioHandler. Message was: "+message)
                alexaresponse = requests.get('https://helloalexa.herokuapp.com/audio', params={'text': message})
                print(alexaresponse.text)


                bot.send_text_message(recipient_id, alexaresponse.text)
            else:
                pass
        self.set_status(200)
        self.finish()

    def write_error(self, status_code, **kwargs):
        self.write("Gosh darnit, user! You caused a %d error." % status_code)

              
old audio version  
class AudioHandler(BaseHandler):
    # @tornado.web.authenticated
    @tornado.web.asynchronous
    def post(self):
        print("getting post...")#
        uid = tornado.escape.xhtml_escape(self.current_user)
        token = gettoken(uid)
        #token="Atza|IQEBLjAsAhRJ93F6BuePKbGRq-vjCnBz0KZ6_wIUYvHgwQ-gTNF6VIl21S-XimwC09K-WkyDysOpP31HjIcQNgkrI9QXEaIA6erpmAaV_TgecgPgQjYVgkDNloyPw9mJjdBpA2dFhzYIi0LfryCHlbeUb1KwzwItvM7RNRAKDonhHhzYu27L52VOEpGkz7GWJCjRtDMQE7_pxCFVQ8JA8QijDfsaMDTJEuZ9hL-SezRMyjzce42vYBq6orJrfXqILnfZQzm4PNKcCc_4E59Mmgfppz5HcDtwjWfAOvWrWFfpLi_Gi19QyUCmPeI5u6806aqY23wcqMLvHXA8L9L2kQ05fv_UtD9Ry2DYySyLFwnnGbWnFZNz7yEWTF25w2ZHzYYvMFF2y_irIIQEvC07xm2jOLypDoOq1Ofzya8YscoP3HLTukQit1rPk8y8eCnPKoytjM371VI5FM2FKx2CvAs6k3Yku0rVsvVCQxwDFMQGFCVjqNWMjuNlm4tZnh8gk0gox0wmL7yhHqhbos3qu4jPux-wnRLx3IbHw7rtQtTnY7vNr5UvbRExXSgLwH5zMiu4"
        if (token == False):
            self.set_status(403)
        else:
            print("geting argument...")
            # phrase=self.get_argument("text", default=None, strip=False)
            # print(phrase)
            phrase = "What is 22 divided by 2?"
            audio = requests.get('https://api.voicerss.org/', params={'key': '970f71e61a4b4c8abd6af0d1f6a5326e', 'src': phrase, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})
            rxfile = audio.content
            #Response(audio.content, mimetype='audio/mpeg')
            #print("audio.content:  ", audio.content)
            #rxfile = self.request.files['data'][0]['body']
            tf = tempfile.NamedTemporaryFile(suffix=".wav")
            tf.write(rxfile)
            _input = AudioSegment.from_wav(tf.name)
            tf.close()

            #print("TF:  ", tf)
            #print("RX:  ", rxfile)

            tf = tempfile.NamedTemporaryFile(suffix=".wav")
            output = _input.set_channels(1).set_frame_rate(16000)
            f = output.export(tf.name, format="wav")
            url = 'https://access-alexa-na.amazon.com/v1/avs/speechrecognizer/recognize'
            headers = {'Authorization' : 'Bearer %s' % token}
            d = {
                "messageHeader": {
                    "deviceContext": [
                        {
                            "name": "playbackState",
                            "namespace": "AudioPlayer",
                            "payload": {
                                "streamId": "",
                                "offsetInMilliseconds": "0",
                                "playerActivity": "IDLE"
                            }
                        }
                    ]
                },
                "messageBody": {
                    "profile": "alexa-close-talk",
                    "locale": "en-us",
                    "format": "audio/L16; rate=16000; channels=1"
                }
            }
            files = [
                ('file', ('request', json.dumps(d), 'application/json; charset=UTF-8')),
                ('file', ('audio', tf, 'audio/L16; rate=16000; channels=1'))
            ]   
            r = requests.post(url, headers=headers, files=files)
            tf.close()
            for v in r.headers['content-type'].split(";"):
                if re.match('.*boundary.*', v):
                    boundary =  v.split("=")[1]
            data = r.content.split(boundary)
            for d in data:
                if (len(d) >= 1024):
                   audio = d.split('\r\n\r\n')[1].rstrip('--')


            tf2 = tempfile.NamedTemporaryFile(suffix=".mp3")
            tf2.write(audio)
            _input2 = AudioSegment.from_mp3(tf2.name)
            tf2.close()

            tf3 = tempfile.NamedTemporaryFile(suffix=".wav")
            output2=_input2.export(tf3.name, format="wav")


            r = sr.Recognizer()
            with sr.AudioFile(tf3) as source:
                audio2 = r.record(source) # read the entire audio file

            # recognize speech using Wit.ai
            print(token)
            WIT_AI_KEY = "ACGKCNOEUUXXHU3Q2SOMVCZW3MQMYUNW" # Wit.ai keys are 32-character uppercase alphanumeric strings
            try:
                transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
                print("Wit.ai thinks you said " + transcription )
            except sr.UnknownValueError:
                print("Wit.ai could not understand audio")
            except sr.RequestError as e:
                print("Could not request results from Wit.ai service; {0}".format(e))

             












            self.set_header('Content-Type', 'audio/mpeg')
            self.write(audio)

            # self.set_header('Content-Type', 'text/plain')
            # self.write(transcription)
            self.finish()


# #new text version
# class AudioHandler(BaseHandler):
#     # @tornado.web.authenticated
#     @tornado.web.asynchronous
#     def get(self):
#         print("getting post...")#
#         # uid = tornado.escape.xhtml_escape(self.current_user)
#         # token = gettoken(uid)
#         token="Atza|IQEBLjAsAhRp4vLXzSI4dlFJwGXuacnDExwWJgIUFnwVxSpnECYvChPubH9a0hKDbtFnhy2rNwfmFfQFOdUIiE6EqT7Et-maLe0oeIcahPOGPPWMu0RG6PG2KpdbyDsdjEc5zZ3EFWMnXmU89ZFuMzAbW1rIODJdhun0cE9AHcuyfUk0HEQx2OhvutXVuAzcRvLpvAqxw1sIz_n1qyz2VQ_eD4aQlhZX9aDbQ9b0pmX_nFi3RYZlFBzH1UmnzBBnCdoCGPb2s0WBTvSg6-judGJljZtli862o5nVkwlvsxOZ0Ze8a_z8Q-lnynx-BpAdESMIPsFi73DDGIbHxiLN0dvXVZ2tipKXvudX-5_v-4BQ-IpJw4QXpTUcRC2qzocarm6FpIiyLM_fKdgyrmmPS2obHHct3vKLtWMrdXH_9MBzEv0wjmYpPEX5oTHhaOIT68Z5dBuKWZwXICFD1OwP0XuN6HbgUeKeFSH4DYe3hbnlkCb5qz_ImAMWnVteZU2pS_LH5h8o1lfaHT0YSoke_qkAX7OsFAWZ33z8243l63RzI8k"
#         if (token == False):
#             self.set_status(403)
#         else:
#             print("geting argument...")
#             phrase=self.get_argument("text", default=None, strip=False)
#             print(phrase)
#             # phrase = "What is 22 divided by 2?"
#             audio = requests.get('https://api.voicerss.org/', params={'key': '970f71e61a4b4c8abd6af0d1f6a5326e', 'src': phrase, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})
#             rxfile = audio.content
#             #Response(audio.content, mimetype='audio/mpeg')
#             #print("audio.content:  ", audio.content)
#             #rxfile = self.request.files['data'][0]['body']
#             tf = tempfile.NamedTemporaryFile(suffix=".wav")
#             tf.write(rxfile)
#             _input = AudioSegment.from_wav(tf.name)
#             tf.close()

#             #print("TF:  ", tf)
#             #print("RX:  ", rxfile)

#             tf = tempfile.NamedTemporaryFile(suffix=".wav")
#             output = _input.set_channels(1).set_frame_rate(16000)
#             f = output.export(tf.name, format="wav")
#             url = 'https://access-alexa-na.amazon.com/v1/avs/speechrecognizer/recognize'
#             headers = {'Authorization' : 'Bearer %s' % token}
#             d = {
#                 "messageHeader": {
#                     "deviceContext": [
#                         {
#                             "name": "playbackState",
#                             "namespace": "AudioPlayer",
#                             "payload": {
#                                 "streamId": "",
#                                 "offsetInMilliseconds": "0",
#                                 "playerActivity": "IDLE"
#                             }
#                         }
#                     ]
#                 },
#                 "messageBody": {
#                     "profile": "alexa-close-talk",
#                     "locale": "en-us",
#                     "format": "audio/L16; rate=16000; channels=1"
#                 }
#             }
#             files = [
#                 ('file', ('request', json.dumps(d), 'application/json; charset=UTF-8')),
#                 ('file', ('audio', tf, 'audio/L16; rate=16000; channels=1'))
#             ]   
#             r = requests.post(url, headers=headers, files=files)
#             tf.close()
#             for v in r.headers['content-type'].split(";"):
#                 if re.match('.*boundary.*', v):
#                     boundary =  v.split("=")[1]
#             data = r.content.split(boundary)
#             for d in data:
#                 if (len(d) >= 1024):
#                    audio = d.split('\r\n\r\n')[1].rstrip('--')


#             tf2 = tempfile.NamedTemporaryFile(suffix=".mp3")
#             tf2.write(audio)
#             _input2 = AudioSegment.from_mp3(tf2.name)
#             tf2.close()

#             tf3 = tempfile.NamedTemporaryFile(suffix=".wav")
#             output2=_input2.export(tf3.name, format="wav")


#             r = sr.Recognizer()
#             with sr.AudioFile(tf3) as source:
#                 audio2 = r.record(source) # read the entire audio file

#             # recognize speech using Wit.ai
#             print(token)
#             WIT_AI_KEY = "ACGKCNOEUUXXHU3Q2SOMVCZW3MQMYUNW" # Wit.ai keys are 32-character uppercase alphanumeric strings
#             try:
#                 transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
#                 print("Wit.ai thinks you said " + transcription )
#             except sr.UnknownValueError:
#                 print("Wit.ai could not understand audio")
#             except sr.RequestError as e:
#                 print("Could not request results from Wit.ai service; {0}".format(e))

             









#             # self.set_header('Content-Type', 'audio/mpeg')
#             # self.write(audio)

#             self.set_header('Content-Type', 'text/plain')
#             self.write(transcription)
#             self.finish()



def main():
    settings = {
        "cookie_secret": "parisPOLANDbroadFENCEcornWOULD",
        "login_url": "/static/welcome.html",
    }
    static_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    application = tornado.web.Application([(r"/", MainHandler),
                                            (r"/start", StartAuthHandler),
                                            (r"/code", CodeAuthHandler),
                                            (r"/logout", LogoutHandler),
                                            (r"/audio", AudioHandler),
                                            (r"/webhook", MessageHandler),
                                            (r'/(favicon.ico)', tornado.web.StaticFileHandler,{'path': static_path}),
                                            (r'/static/(.*)', tornado.web.StaticFileHandler, {'path': static_path}),
                                            ], **settings)
    http_server = tornado.httpserver.HTTPServer(application)
    port = int(os.environ.get("PORT", 5000))
    http_server.listen(port)
    tornado.ioloop.IOLoop.instance().start()

if __name__ == "__main__":
    main()
    
    

