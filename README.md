# AlexaBot

With Amazon Alexa as a Facebook contact, you can quietly message Alexa and ask her to turn off the oven you left on while you're in the middle of a meeting. AlexaBot makes use of Amazon's Alexa Voice Service API using sammachin's alexaweb core code. However, the API only takes in and returns audio. I found a hacky workaround by going text->speech->AVS->audio->text using VoiceRSS and wit.ai. To make things even more convenient, AlexaBot is integrated with Facebook's new Messenger Platform as a chatbot relaying messages to this server. Also set up a REST API for other products to take advantage of the Alexa text API Amazon never offered.

To fork, obtain the credentials required in creds.py (stored in Heroku in this case). Requirements are in requirements.txt. Python, Redis required. FFMPEG required.


![alt tag](https://lh3.googleusercontent.com/iiBJOLqmzOWImrjXCsd4KJfKTUM-7fyCuL2lyNyJMyrwhLnyPcitCiS1gRcaAEFnV0VB0xdOO02PdWlXS9yMNkYoyq8Eu_7dAYrp9znwhPqIzWmDJ9AESj1C__oWJcP8Fha-bzOi-imJN0aQo5_IEVHnhgSeqXRHRQcRMJCf09XumJHlX_650Lx1ilIbMzGxQanp6iz9OwqyHRJvnIZ-nBncrAuY_IeuQtD2jSP1jfNCZCXxlmLa0CaP3uHjvHNcYEj0iEPuhr8IaGSujevJmP7kqxu31wmKH6vMBdJIMHJsAk6x6pKEoDj3xlukjnXOC4hPRzfIjuMXel3WOeuJv8cddFKOnEUyGDyn0jCfBWcYKcwDZC4x2dcj35zJ7uh7Lpu2Nn3mItlHUfb08pDoi2UDhy918Lsra7Kp2VJz1vJQnKa2ovyCDVJuLFF5sTLUuksCQ6Nu5RULARP2S-jIRi2cUkSFn6WuY9shZtcfu5j8i9VJ6PJxDO3wl-KrRjwUyPOdiRA8KgTyZQS8q9h4j_W5QBKVGjnGjKngattojkxdb4DHy4pfPslsmYeOU4sfCHByCa8Ve2fTeLIr_o1IERgSo1sH1NwaGZ1TlX-hnA=w670-h1188-no)
