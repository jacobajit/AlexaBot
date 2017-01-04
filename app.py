import os
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.template
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
# import speech_recognition as sr
from pymessenger.bot import Bot
import traceback

from pyDubMod import *

from timeout_dec import timeout_dec  # timeout decorator


TOKEN= Facebook_Token
bot = Bot(TOKEN)


def shutil_which(pgm):
    """Python 2 backport of ``shutil.which()`` from Python 3"""
    path = os.getenv('PATH')
    for p in path.split(os.path.pathsep):
        p = os.path.join(p, pgm)
        if os.path.exists(p) and os.access(p, os.X_OK):
            return p

    
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
@timeout_dec(20)
def getAlexa(text,mid):
        print("getting post...")#
        # uid = tornado.escape.xhtml_escape(self.current_user)
        token = gettoken(mid)
        #token=""
        if (token == False):
            red = redis.from_url(redis_url)
            red.delete(mid+"-refresh_token")
            return "Sorry, it looks like you didn't log in to Amazon correctly. Try again here https://amazonalexabot.herokuapp.com/start and come back with your code."
        else:
            print("geting argument...")
            phrase=text
            print(phrase)
            #http://translate.google.com/translate_tts?ie=UTF-8&total=1&idx=0&textlen=32&client=tw-ob&q=hello&tl=En-us
            audio = requests.get('https://api.voicerss.org/', params={'key': VoiceRSS_Token, 'src': phrase, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})
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

            #convert mp3 file to wav
            tf3 = tempfile.NamedTemporaryFile(suffix=".wav")
            #output2=_input2.export(tf3.name, format="wav",bitrate="16k",parameters=["-ac", "1", "-acodec", "pcm_s16le"])
            output2=_input2.export(tf3.name, format="wav")
 
            r = Recognizer()
            with AudioFile(tf3) as source:
                audio2 = r.record(source) # read the entire audio file

           # # recognize speech using Microsoft Bing Voice Recognition
           #  BING_KEY = "578545f1fb3940fb99151cfd79b476b1" # Microsoft Bing Voice Recognition API keys 32-character lowercase hexadecimal strings
           #  try:
           #      print("Microsoft Bing Voice Recognition thinks you said " + r.recognize_bing(audio2, key=BING_KEY))
           #  except UnknownValueError:
           #      print("Microsoft Bing Voice Recognition could not understand audio")
           #  except RequestError as e:
           #      print("Could not request results from Microsoft Bing Voice Recognition service; {0}".format(e))

            # recognize speech using Google Speech Recognition
            try:
                # for testing purposes, we're just using the default API key
                # to use another API key, use `r.recognize_google(audio, key="GOOGLE_SPEECH_RECOGNITION_API_KEY")`
                # instead of `r.recognize_google(audio)`
                transcription=r.recognize_google(audio2, key=Google_Speech_Token)
                print("Google Speech Recognition thinks you said " + transcription)
            except (UnknownValueError, RequestError):
                 # recognize speech using Wit.ai
                print(token)
                WIT_AI_KEY = Wit_Token # Wit.ai keys are 32-character uppercase alphanumeric strings
                try:
                    transcription=r.recognize_wit(audio2, key=WIT_AI_KEY)
                    print("Wit.ai thinks you said " + transcription)
                except UnknownValueError:
                    print("Wit.ai could not understand audio")
                except RequestError as e:
                    print("Could not request results from Wit.ai service; {0}".format(e))

                print("Google Speech Recognition could not understand audio")

            return transcription

    
class BaseHandler(tornado.web.RequestHandler):
    def get_current_user(self):
        return self.get_cookie("user")


class MainHandler(BaseHandler):
    # @tornado.web.authenticated
    @tornado.web.asynchronous
    def get(self):
        self.render("static/tokengenerator.html", token=self.get_argument("refreshtoken"))


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
        if mid != None:
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
        path = "https" + "://" + self.request.host 
        callback = path+"/code"
        payload = {"client_id" : Client_ID, "client_secret" : Client_Secret, "code" : code, "grant_type" : "authorization_code", "redirect_uri" : callback }
        url = "https://api.amazon.com/auth/o2/token"
        r = requests.post(url, data = payload)
        red = redis.from_url(redis_url)
        resp = json.loads(r.text)
        if mid != None:
            print("fetched MID: ",mid)
            red.set(mid+"-access_token", resp['access_token'])
            red.expire(mid+"-access_token", 3600)
            red.set(mid+"-refresh_token", resp['refresh_token'])
            self.render("static/return.html")
            bot.send_text_message(mid, "Great, you're logged in. Start talking to Alexa!")
        else:
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
            if "postback" in x and "payload" in x['postback']:
                payload = x['postback']['payload']
                if payload=="AUTH":
                    print("Generating login link...")
                    link='https://amazonalexabot.herokuapp.com/start?mid='+recipient_id
                    messageData = {"attachment": {"type": "template","payload": {"template_type": "generic","elements": [{"title": "Login to Amazon","buttons": [{"type": "web_url","url": link,"title": "Login"}]}]}}}
                    payload = {"recipient": {"id": recipient_id}, "message": messageData}
                    r = requests.post("https://graph.facebook.com/v2.6/me/messages?access_token="+TOKEN, json=payload)
                    print(r.text)
                    print("Made post request")
            elif "message" in x and "sticker_id" in x["message"]:
                print("received sticker")
                bot.send_text_message(recipient_id, "(y)")
            elif "message" in x and "text" in x['message']:
                message = x['message']['text']
                print("The message:", message)
                try:
                    if message.lower() in {"hi", "hello", "hi alexa", "hello alexa","hi there","hey alexa","hey", "hello there"}:
                        bot.send_text_message(recipient_id, "Hi there")
                    elif message.lower() in {"help", "help me"}:
                        bot.send_text_message(recipient_id, "Type anything you would say to Amazon's Alexa assistant and receive her response. For more help with what you can say, check out the Things to Try section of the Alexa app.")
                    else:
                        red = redis.from_url(redis_url)
                        if not red.exists(recipient_id+"-refresh_token"):
                            print("Received refresh token")
                            red.set(recipient_id+"-refresh_token", message)
                            testing=gettoken(recipient_id)
                            if(testing==False):
                                red.delete(recipient_id+"-refresh_token")
                                link='https://amazonalexabot.herokuapp.com/start?mid='+recipient_id
                                messageData = {"attachment": {"type": "template","payload": {"template_type": "generic","elements": [{"title": "You are not logged in properly.","buttons": [{"type": "web_url","url": link,"title": "Login"}]}]}}}
                                payload = {"recipient": {"id": recipient_id}, "message": messageData}
                                r = requests.post("https://graph.facebook.com/v2.6/me/messages?access_token="+TOKEN, json=payload)
                            else:
                                bot.send_text_message(recipient_id, "Great, you're logged in. Start talking to Alexa!")
                          
                        else:
                            print("Getting Alexa's response from AudioHandler. Message was: "+message)
                            # alexaresponse = requests.get('https://amazonalexabot.herokuapp.com/audio', params={'text': message})
                            alexaresponse = getAlexa(message,recipient_id)
                            print("Alexa's response: ", alexaresponse)
                            # bot.send_text_message(recipient_id, alexaresponse.text)
                            if len(alexaresponse) > 320:
                                alexaresponse = alexaresponse[:317] + "..."
                            bot.send_text_message(recipient_id, alexaresponse)
                except TimeoutError:
                    print(traceback.format_exc())
                    bot.send_text_message(recipient_id, "Request took too long.")
                except Exception,err:
                    print("Couldn't understand: ", traceback.format_exc())
                    bot.send_text_message(recipient_id, "Alexa gave an invalid response. This may occur if you gave Alexa a command such as \"Turn on the lights,\" which requires no reply from Alexa. Otherwise, something went wrong and we are trying to fix it!")
            else:
                pass
        self.set_status(200)
        self.finish()

    def write_error(self, status_code, **kwargs):
        self.write("Gosh darnit, user! You caused a %d error." % status_code)


def main():
    settings = {
        "cookie_secret": "parisPOLANDbroadFENCEcornWOULD",
        # url
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

