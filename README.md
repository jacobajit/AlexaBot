# AlexaBot

Type to Alexa!

With Amazon Alexa as a Facebook contact, you can quietly message Alexa and ask her to turn off the oven you left on while you're in the middle of a meeting. AlexaBot makes use of Amazon's Alexa Voice Service API using sammachin's alexaweb core code. However, the AVS API only takes in and returns audio. I found a hacky workaround by going from text->speech->AVS->audio->text using VoiceRSS and Google Cloud Speech. For convenience, AlexaBot is integrated with Facebook's Messenger Platform as a chatbot relaying messages to this server.

To fork, obtain the credentials required in creds.py (stored in Heroku in this case). Requirements are in requirements.txt. Python, Redis required. FFMPEG required.


<img src="https://i.imgur.com/LUFY5wm.png" alt="Smiley face" width=300>
