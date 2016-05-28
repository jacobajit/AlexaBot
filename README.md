# AlexaBot

With Amazon Alexa as a Facebook contact, you can quietly message Alexa and ask her to turn off the oven you left on while you're in the middle of a meeting. AlexaBot makes use of Amazon's Alexa Voice Service API. However, the API only takes in and returns audio. I found a hacky workaround by going text->speech->AVS->audio->text using VoiceRSS and wit.ai. To make things even more convenient, AlexaBot is integrated with Facebook's new Messenger Platform as a chatbot relaying messages to this server. Also set up a REST API for other products to take advantage of the Alexa text API Amazon never offered.

To fork, obtain the credentials required in creds.py (stored in Heroku in this case). Requirements are in requirements.txt. Python, Redis required. FFMPEG required.

![alt tag](https://scontent-iad3-1.xx.fbcdn.net/t31.0-8/13254944_960071984112229_6094048875208261512_o.jpg)


