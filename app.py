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
from pymessenger.bot import Bot
import traceback

# PyDub has some issues with Google Speech API params - fixed in pyDubMod
from pyDubMod import *

# Timeout decorator
from timeout_dec import timeout_dec

bot = Bot(Facebook_Token)

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

# Get Alexa's [text] response to a [text] query
@timeout_dec(20)
def getAlexa(text, mid):
    # Fetch user's Amazon access token with Messenger ID as the uid
    token = gettoken(mid)

    # Nonexistent or broken refresh token - was more of an issue in older version, when user manually entered refresh token
    if (not token):
        # Remove any broken refresh token
        red = redis.from_url(redis_url)
        red.delete(mid + "-refresh_token")
        return "Sorry, it looks like you didn't log in to Amazon correctly. Try again here https://amazonalexabot.herokuapp.com/start and come back with your code."

    # Google Translate TTS was also considered -
    # http://translate.google.com/translate_tts?ie=UTF-8&total=1&idx=0&textlen=32&client=tw-ob&q=hello&tl=En-us

    # Speech synthesis through VoiceRSS API
    audio = requests.get('https://api.voicerss.org/', params={'key': VoiceRSS_Token, 'src': text, 'hl': 'en-us', 'c': 'WAV', 'f': '16khz_16bit_mono'})

    # Write out synthesized speech to a temporary file
    tf = tempfile.NamedTemporaryFile(suffix=".wav")
    tf.write(audio.content)

    # Create an AudioSegment object from synthesized audio file
    _input = AudioSegment.from_wav(tf.name)
    tf.close()

    # Convert audio object - mono channel 16 khz for Alexa Voice Service
    _output = _input.set_channels(1).set_frame_rate(16000)

    # Formatted synthesized audio file
    audio_infile = _output.export(format="wav")

    # Parameters for AVS request
    url = 'https://access-alexa-na.amazon.com/v1/avs/speechrecognizer/recognize'
    headers = {'Authorization' : 'Bearer %s' % token}
    avs_json = {
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
        ('file', ('request', json.dumps(avs_json), 'application/json; charset=UTF-8')),
        ('file', ('audio', audio_infile, 'audio/L16; rate=16000; channels=1'))
    ]   

    # Make request to AVS
    r = requests.post(url, headers=headers, files=files)

    for v in r.headers['content-type'].split(";"):
        if re.match('.*boundary.*', v):
            boundary =  v.split("=")[1]

    data = r.content.split(boundary)
    for d in data:
        if (len(d) >= 1024):
           audio_outfile = d.split('\r\n\r\n')[1].rstrip('--')

    # Temporary file to store Alexa audio output
    tf = tempfile.NamedTemporaryFile(suffix=".mp3")
    tf.write(audio_outfile)

    # Create AudioSegment object for Alexa audio output
    _input = AudioSegment.from_mp3(tf.name)
    tf.close()

    # Export Alexa audio output in wav format
    wav_audio_outfile =_input.export(tf3.name, format="wav")

    # Speech recognizer object initialization
    r = Recognizer()
    with AudioFile(wav_audio_outfile) as source:
        audio = r.record(source) # read the entire audio file

    # Recognize speech using Google Speech Recognition
    try:
        transcription = r.recognize_google(audio, key=Google_Speech_Token)

    # Fallback speech recognition
    except (UnknownValueError, RequestError):
        print("Google Speech Recognition could not understand audio")

         # Recognize speech using Wit.ai
        WIT_AI_KEY = Wit_Token # Wit.ai keys are 32-character uppercase alphanumeric strings
        try:
            transcription = r.recognize_wit(audio, key=WIT_AI_KEY)
            print("Wit.ai thinks you said " + transcription)
        except UnknownValueError:
            print("Wit.ai could not understand audio")
        except RequestError as e:
            print("Could not request results from Wit.ai service; {0}".format(e))

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

# Facebook Messenger webhook
class MessageHandler(BaseHandler):
    
    # Verify webhook
    @tornado.web.asynchronous
    def get(self):
        if (self.get_argument("hub.verify_token", default=None, strip=False) == "my_voice_is_my_password_verify_me"):
            self.set_header('Content-Type', 'text/plain')
            self.write(self.get_argument("hub.challenge", default=None, strip=False))
            self.finish()
    
    # Receive messages from users
    def post(self):
        fb_json = tornado.escape.json_decode(self.request.body) 
        event = fb_json['entry'][0]['messaging']
        
        for x in event:
            # User's messenger ID (MID)
            recipient_id = x['sender']['id']
            
            # Get Started button - used for AVS authentication
            if "postback" in x and "payload" in x['postback']:
                payload = x['postback']['payload']
                
                # User authentication for AVS
                if payload == "AUTH":
                    # Generate login link with user's MID
                    link = "https://amazonalexabot.herokuapp.com/start?mid=" + recipient_id
                    
                    # Send a login dialog to user in Messenger
                    messageData = {"attachment": {"type": "template","payload": {"template_type": "generic","elements": [{"title": "Login to Amazon","buttons": [{"type": "web_url","url": link,"title": "Login"}]}]}}}
                    payload = {"recipient": {"id": recipient_id}, "message": messageData}
                    r = requests.post("https://graph.facebook.com/v2.6/me/messages?access_token="+Facebook_Token, json=payload)

            # Received sticker
            elif "message" in x and "sticker_id" in x["message"]:
                bot.send_text_message(recipient_id, "(y)")
           
            # Received a textual message
            elif "message" in x and "text" in x["message"]:
                message = x["message"]["text"]
                try:
                    # Hardcode a few greetings that are problematic for the speech synthesis
                    if message.lower() in {"hi", "hello", "hi alexa", "hello alexa","hi there","hey alexa","hey", "hello there"}:
                        bot.send_text_message(recipient_id, "Hi there")
                        
                    # Help message required by Facebook
                    elif message.lower() in {"help", "help me"}:
                        bot.send_text_message(recipient_id, "Type anything you would say to Amazon's Alexa assistant and receive her response. For more help with what you can say, check out the Things to Try section of the Alexa app.")
                    
                    # Normal textual message
                    else:
                        red = redis.from_url(redis_url)
                        
                        # User is not/improperly logged into Amazon - used to handle direct text refresh tokens here
                        if not red.exists(recipient_id+"-refresh_token"):
                            # Generate login link with user's MID
                            link='https://amazonalexabot.herokuapp.com/start?mid='+recipient_id
                            
                            # Send login dialog to user in Messenger
                            messageData = {"attachment": {"type": "template","payload": {"template_type": "generic","elements": [{"title": "You are not logged in properly.","buttons": [{"type": "web_url","url": link,"title": "Login"}]}]}}}
                            payload = {"recipient": {"id": recipient_id}, "message": messageData}
                            r = requests.post("https://graph.facebook.com/v2.6/me/messages?access_token="+Facebook_Token, json=payload)
                        
                        # User is logged into Amazon
                        else:
                            # Get response from Alexa - convert text-to-speech, pass through AVS, and then convert speech-to-text
                            alexa_response = getAlexa(message, recipient_id)
                            
                            # Truncate response
                            if len(alexa_response) > 320:
                                alexa_response = alexaresponse[:317] + "..."
                                
                            # Send Alexa's textual response to Messenger user
                            bot.send_text_message(recipient_id, alexa_response)
                            
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

def main():
    settings = {
        "cookie_secret": "parisPOLANDbroadFENCEcornWOULD",
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

