# AlexaBot

With Amazon Alexa as a Facebook contact, you can quietly message Alexa and ask her to turn off the oven you left on while you're in the middle of a meeting. AlexaBot makes use of Amazon's Alexa Voice Service API. However, the API only takes in and returns audio. I found a hacky workaround by going text->speech->AVS->audio->text using VoiceRSS and wit.ai. To make things even more convenient, AlexaBot is integrated with Facebook's new Messenger Platform as a chatbot relaying messages to this server. Also set up a REST API for other products to take advantage of the Alexa text API Amazon never offered.

To fork, obtain the credentials required in creds.py (stored in Heroku in this case). Requirements are in requirements.txt. Python, Redis required. FFMPEG required.

![alt tag](https://lh3.googleusercontent.com/44PtdZRhTbGQWKsUC3umjrNBPRhB_RNdmN6DvSeRrQSUjXklMp7xY6VHEDO-dAaOWDSgdvDZNK0WTpgkLAxKQRkBBdJLgsX9PsSlEj-TC0wndWpl6mluee-BRCVZT6AHb3KKOy9H2SUc2DzXfMjjZTMtxEdsecBpYeoWm92hjDJnz1vfOUOjpSXGeGMm9VIqS3KR2gtIZjV4Dqpsr8hmXJNZQyAv8V5YDX-D1V2zUUsTejSz6RKoNPRtF5OIO-z5f4Vui-aLYWOELHc-VYdw0n4TFoJNXjm39XcgFZb7VQT31GuXtO64qlROIW8IwMOkZ4kDiV3X58TonfSQTjV514qnyBBTbJxV0RypV3d19JLr-DH21IFgn2ZTJLDpWn1c16sUubyRnU1JQ_Gx9sMlmnzJxTVg5NDPee2sLKw_IKdxpkwt1eGbnBWCxvw3TzJKjIWkUGkztR_yOBdF0Yo7BPNH4mpq0Vf3q87ajZcnRy6f4bcztBXdi-4sspi7fjosy5O_CQ_oxh5rEJn2n0HeWWzFFSvrBfi71wHP2pGwN6fIJHRqRNI4IRSG9AfKoP-Z5fse58jHIiaE0FQQkCKlj2LzRP_MGGE=w674-h1198-no)


