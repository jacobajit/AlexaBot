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
import string
from pydub import AudioSegment
import speech_recognition as sr
from pymessenger.bot import Bot



TOKEN= Facebook_Token
bot = Bot(TOKEN)
    
def gettoken(uid):
    red = redis.from_url(redis_url)
    token = red.get(uid+"-access_token")
    refresh = red.get(uid+"-refresh_token")
    if token:
        return token
    elif refresh:
        #good refresh token
        try:
            payload = {"client_id" : Client_ID, "client_secret" : Client_Secret, "refresh_token" : refresh, "grant_type" : "refresh_token", }
            url = "https://api.amazon.com/auth/o2/token"
            r = requests.post(url, data = payload)
            resp = json.loads(r.text)
            red.set(uid+"-access_token", resp['access_token'])
            red.expire(uid+"-access_token", 3600)
            return resp['access_token']
        #bad refresh token
        except:
            return False
    else:
        return False

#function version of getting Alexa's response in text
def getAlexa(text,mid):
        print("getting post...")#
        # uid = tornado.escape.xhtml_escape(self.current_user)
        token = gettoken(mid)
        #token=""
        if (token == False):
            red = redis.from_url(redis_url)
            red.delete(mid+"-refresh_token")
            return "Sorry, it looks like you didn't log in to Amazon correctly. Try again here https://helloalexa.herokuapp.com/start and come back with your code."
        else:

            print("geting argument...")
            phrase=text
            print(phrase)
            # exclude = set(string.punctuation)
            # phrase = ''.join(ch for ch in phrase if ch not in exclude)
            # if (phrase != ""):

            # phrase = "What is 22 divided by 2?"
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
            WIT_AI_KEY = Wit_Token # Wit.ai keys are 32-character uppercase alphanumeric strings
            try:
                transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
                print("Wit.ai thinks you said " + transcription )
            except sr.UnknownValueError:
                print("Wit.ai could not understand audio")
            except sr.RequestError as e:
                print("Could not request results from Wit.ai service; {0}".format(e))


            return transcription

    
class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        return self.get_cookie("user")


class MainHandler(BaseHandler):
    @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        self.set_header('Content-Type', 'text/plain')
        self.write("Copy and paste this code into AlexaBot: \n \n"+self.get_argument("refreshtoken", default=None, strip=False))
        self.finish()


class StartAuthHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        mid=self.get_argument("mid", default=None, strip=False)
        scope="alexa_all"
        sd = json.dumps({
            "alexa:all": {
                "productID": Product_ID,
                "productInstanceAttributes": {
                    "deviceSerialNumber": "1"
                }
            }
        })
        url = "https://www.amazon.com/ap/oa"
        path = "https" + "://" + self.request.host 
        print("boo")
        self.set_cookie("user", mid)
        callback = path + "/code"
        payload = {"client_id" : Client_ID, "scope" : "alexa:all", "scope_data" : sd, "response_type" : "code", "redirect_uri" : callback }
        req = Request('GET', url, params=payload)
        p = req.prepare()
        self.redirect(p.url)


class CodeAuthHandler(tornado.web.RequestHandler):
    @tornado.web.asynchronous
    def get(self):
        code=self.get_argument("code")
        mid=self.get_cookie("user")
        print("fetched MID: ",mid)
        path = "https" + "://" + self.request.host 
        callback = path+"/code"
        payload = {"client_id" : Client_ID, "client_secret" : Client_Secret, "code" : code, "grant_type" : "authorization_code", "redirect_uri" : callback }
        url = "https://api.amazon.com/auth/o2/token"
        r = requests.post(url, data = payload)
        uid = str(uuid.uuid4())
        red = redis.from_url(redis_url)
        resp = json.loads(r.text)
        red.set(mid+"-access_token", resp['access_token'])
        red.expire(mid+"-access_token", 3600)
        red.set(mid+"-refresh_token", resp['refresh_token'])
        self.redirect("/?refreshtoken="+resp['refresh_token'])                  

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
        if (self.get_argument("hub.verify_token", default=None, strip=False) == "my_voice_is_my_password_verify_me"):
            self.set_header('Content-Type', 'text/plain')
            self.write(self.get_argument("hub.challenge", default=None, strip=False))
            self.finish()

    def post(self):
        output = tornado.escape.json_decode(self.request.body) 
        print("OUTPUT: ",output)
        event = output['entry'][0]['messaging']
        for x in event:
            recipient_id = x['sender']['id']
            if x.get('postback') and x['postback'].get('payload'):
                payload = x['postback']['payload']
                if payload=="AUTH":
                    print("Generating login link...")
                    link='https://helloalexa.herokuapp.com/start?mid='+recipient_id
                    bot.send_text_message(recipient_id, "Log into Amazon at "+link)
            elif (x.get('message') and x['message'].get('text')):
                message = x['message']['text']
                print("The message:", message)
                try:
                    red = redis.from_url(redis_url)
                    if not red.exists(recipient_id+"-refresh_token"):
                        print("Received refresh token")
                        red.set(recipient_id+"-refresh_token", message)
                        testing=gettoken(recipient_id)
                        if(testing==False):
                            red.delete(recipient_id+"-refresh_token")
                            bot.send_text_message(recipient_id, "Sorry, that looks like an invalid token. Try again here https://helloalexa.herokuapp.com/start and come back with your code.")
                        else:
                            bot.send_text_message(recipient_id, "Great, you are logged in. Start talking to Alexa!")
                        #bot.send_text_message(recipient_id,"Hey there, I'm AlexaBot! Please click on the following link to connect to you Amazon account: https://helloalexa.herokuapp.com/start")
                    else:
                        
                        print("Getting Alexa's response from AudioHandler. Message was: "+message)
                        # alexaresponse = requests.get('https://helloalexa.herokuapp.com/audio', params={'text': message})
                        alexaresponse = getAlexa(message,recipient_id)
                        # bot.send_text_message(recipient_id, alexaresponse.text)
                        bot.send_text_message(recipient_id, alexaresponse)
                except:
                    bot.send_text_message(recipient_id, "Sorry, we couldn't understand your message.")
            else:
                pass
        self.set_status(200)
        self.finish()

    def write_error(self, status_code, **kwargs):
        self.write("Gosh darnit, user! You caused a %d error." % status_code)

#REST API version of getAlexa, pass in token and text, get text back
class AudioHandler(BaseHandler):
    # @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        print("getting post...")#
        # uid = tornado.escape.xhtml_escape(self.current_user)
        # token = gettoken(uid)
        token="" #get argument later
        if (token == False):
            self.set_status(403)
        else:
            print("geting argument...")
            phrase=self.get_argument("text", default=None, strip=False)
            print(phrase)

            # phrase = "What is 22 divided by 2?"
            audio = requests.get('http://www.voicerss.org/controls/speech.ashx', params={'src': phrase, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})
            rxfile = audio.content

            tf = tempfile.NamedTemporaryFile(suffix=".wav")
            tf.write(rxfile)
            _input = AudioSegment.from_wav(tf.name)
            tf.close()

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
            WIT_AI_KEY = Wit_Token # Wit.ai keys are 32-character uppercase alphanumeric strings
            try:
                transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
                print("Wit.ai thinks you said " + transcription )
            except sr.UnknownValueError:
                print("Wit.ai could not understand audio")
            except sr.RequestError as e:
                print("Could not request results from Wit.ai service; {0}".format(e))


            self.set_header('Content-Type', 'text/plain')
            self.write(transcription)
            self.finish()



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
    
    

