import os
import re
import json
import time
import pickle
import random
import asyncio
import logging

from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta
from instagrapi import Client

from fbns_mqtt import fbns_mqtt
from notifications import InstagramNotification


if not "sessions" in os.listdir(): os.mkdir("sessions")

load_dotenv()

logging.basicConfig(
	format='%(asctime)s %(levelname)-8s %(message)s',
	level=logging.INFO,
	datefmt='%Y-%m-%d %H:%M:%S'
)


STOP = asyncio.Event()

class ExtendedClient(Client):
	def register_push(self, token):
		endpoint = "push/register/"
		params = dict(
			device_type="android_mqtt",
			is_main_push_channel=True,
			phone_id=self.phone_id,
			device_token=token,  # fbns_token
			guid=self.uuid,
			users=self.user_id,
		)
		
		res = self.private_request(endpoint, data=params, with_signature=False)
		return res


class InstagramMQTT(ExtendedClient):
	def __init__(self, username, password):
		session = {}
		self.Psettings = {}
		if os.path.exists('settings.json'):
			self.Psettings = json.load(open('settings.json'))
			session = self.Psettings['api_settings']

		super().__init__(session)
		self.login(username, password)

		self.settings_file = Path(f"sessions/{username}_mqtt.pkl")

	def save_settings(self):
		with open(self.get_abs_path('settings.json'), 'w') as f:
			json.dump(self.get_settings(), f, indent=2)

	def save_fbns_settings(self, data):
		with open(self.settings_file, 'wb') as f:
			pickle.dump(data, f)
	
	def get_abs_path(self, x):
		absp = os.path.abspath(os.path.join(os.path.abspath(os.path.dirname(__file__)), x))

		return absp

	def handle_disconnect(self, packet, exc=None):
		# Reconnect
		asyncio.ensure_future(self.reconnect_after_disconnect())

	async def reconnect_after_disconnect(self):
		logging.warning('Disconnected.. Reconnecting')

		await self.listener_worker()

	async def listener_worker(self):
		if os.path.exists(self.get_abs_path(self.settings_file)):
			with open(self.get_abs_path(self.settings_file), 'rb') as f:
				self.settings = pickle.load(f)
		else:
			self.settings = {}

		self.client = fbns_mqtt.FBNSMQTTClient() 
		self.client.on_disconnect = self.handle_disconnect

		fbns_auth = self.settings.get('fbns_auth')
		if fbns_auth:
			self.client.set_fbns_auth(fbns_mqtt.FBNSAuth(fbns_auth))

		self.client.on_fbns_auth = self.on_fbns_auth
		self.client.on_fbns_token = self.on_fbns_token
		self.client.on_fbns_message = self.on_fbns_message

		await self.client.connect('mqtt-mini.facebook.com', 443, ssl=True, keepalive=900)
		await STOP.wait()
		await self.client.disconnect()

	def on_login_callback(self, client):
		self.settings['api_settings'] = client.settings
		self.client = client

		self.save_fbns_settings(self.settings)

	def on_fbns_auth(self, auth):
		self.settings['fbns_auth'] = auth
		self.settings['fbns_auth_received'] = datetime.now()
		
		self.save_fbns_settings(self.settings)

	def on_fbns_token(self, token):
		device_id = self.settings.get('device_id')

		if self.settings.get('fbns_token') == token:
			if "fbns_token_received" in self.settings:
				if self.settings['fbns_token_received'] > datetime.now()-timedelta(hours=24):
					# Do not register token twice in 24 hours
					return

		self.register_push(token)

		self.settings['fbns_token'] = token
		self.settings['fbns_token_received'] = datetime.now()
		self.save_fbns_settings(self.settings)

	def on_fbns_message(self, push):
		if push.payload:
			notification = InstagramNotification(push.payload)
			
			if notification.collapseKey == 'comment':
				pass # TODO
			
			elif notification.collapseKey == 'direct_v2_message':
				if notification.pushCategory == "direct_v2_text":
					# Handle text

					# solo -> badge=1 / network_classification=in_network_canonical_thread
					# group -> badge=2 / network_classification=in_network_group_thread


					msg_thread_id = notification.actionParams['id']

					msg_content = ':'.join(notification.message.split(':')[1:])[1:] # last [1:] remove the leading space
					msg_author = {
						"name": notification.message.split(':')[0].split(' ')[0],
						"id": notification.sourceUserId
					}

					if msg_content[0] == "/": # Might be a cmd
						if msg_content.split(' ')[0][1:] == "setlang":
							arg = msg_content.split(' ')[1].lower()
							if arg in self.puns.keys():
								stgs = self.Psettings

								if notification.network_classification == "in_network_canonical_thread": # PM
									stgs[msg_author['id']] = arg
									msg = f"You successfully set your default language to {arg.upper()}!"

								elif notification.network_classification == "in_network_group_thread": # Group DM
									stgs[msg_thread_id] = arg
									msg = f"You successfully set chat default language to {arg.upper()}!"

								else:
									print(msg_author, msg.network_classification)
									return #wtf

								self.save_settings()

								self.direct_send(
									msg,
									thread_ids=[msg_thread_id]
								)

							else:
								self.direct_send(
									"This language is not yet supported.. Help to support it here: https://github.com/ghrlt/qfbot",
									thread_ids=[msg_thread_id]
								)

							return

					msg_content = msg_content.strip(',;:!?.(){}[]"*') #Punctuation is no more a problem

					# Finding pun
					start = msg_content.split(' ')[-1].lower()

					# Get lang of user/thread, default FR
					lang = self.Psettings.get(msg_thread_id) or self.Psettings.get(msg_author['id']) or "fr"

					plang = self.puns.get(lang)
					if plang: # If language supported
						pwords = plang.get(start)
						if pwords: # If a pun was found
							end = random.choice(pwords)

							self.direct_send(end, thread_ids=[msg_thread_id])

					
				elif notification.pushCategory == "direct_v2_pending":
					msg_thread_id = notification.actionParams['id']
					msg_author = {
						"name": notification.message.split(':')[0],
						"id": notification.sourceUserId
					}


					#thread = self.client.get_direct_thread(thread_id=msg_thread_id, max_messages=1)
					#msg = thread['items'][0]
					#msg_content = msg['text']


					self.direct_send("Hey! I am now activated, have fun!", thread_ids=[msg_thread_id])


				elif notification.pushCategory is None:
					if notification.message.split(' ')[1] == "liked":
						pass

				else:
					print(notification)
					print('---')
					print(self.client.get_direct_thread(notification.actionParams['id']))
			else:
				print(notification)


	@property
	def puns(self):
		with open('puns.json', 'r') as f:
			puns = json.load(f)

		return puns

if __name__ == "__main__":
	loop = asyncio.get_event_loop()

	username, password = os.getenv("ig-username"), os.getenv("ig-password")
	app = InstagramMQTT(username or input("Username? "), password or input("Password? "))

	try:
		loop.run_until_complete(app.listener_worker())
	except asyncio.CancelledError:
		pass
