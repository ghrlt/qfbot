import os
import re
import json
import time
import pickle
import random
import asyncio
import logging
import pydotenv

from pathlib import Path
from datetime import datetime, timedelta
from instagram_private_api import Client, ClientCookieExpiredError, ClientLoginRequiredError

from fbns_mqtt import fbns_mqtt
from notifications import InstagramNotification


if not "sessions" in os.listdir(): os.mkdir("sessions")
if not "settings.json" in os.listdir(): open('settings.json', 'w').write('{}')

env = pydotenv.Environment()

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
			users=self.authenticated_user_id,
		)
		params.update(self.authenticated_params)
		
		res = self._call_api(endpoint, params=params, unsigned=True)
		return res


	def send_direct_message(self, content: str, user_ids: list=[], thread_ids: list=[]):
		"""
			Code adapted directly from adw0rd/instagrapi library
		"""
		assert (user_ids or thread_ids) and not (user_ids and thread_ids), "Specify user_ids or thread_ids, but not both"
		
		method = "text"
		token = str(random.randint(6800011111111111111, 6800099999999999999))
		kwargs = {
			"action": "send_item",
			"is_shh_mode": "0",
			"send_attribution": "direct_thread",
			"client_context": token,
			"mutation_token": token,
			"nav_chain": "1qT:feed_timeline:1,1qT:feed_timeline:2,1qT:feed_timeline:3,7Az:direct_inbox:4,7Az:direct_inbox:5,5rG:direct_thread:7",
			"offline_threading_id": token,
		}
		
		if "http" in content:
			method = "link"
			kwargs["link_text"] = content
			kwargs["link_urls"] = json.dumps(re.findall(r"(https?://[^\s]+)", content))
		else:
			kwargs["text"] = content
		
		if thread_ids:
			kwargs["thread_ids"] = json.dumps([int(tid) for tid in thread_ids])
		if user_ids:
			kwargs["recipient_users"] = json.dumps([[int(uid) for uid in user_ids]])
		
		result = self._call_api(f"direct_v2/threads/broadcast/{method}/", params=kwargs, unsigned=True)
		return result


	def get_direct_thread(self, thread_id: int, max_messages: int=20):
		params = {
			"visual_message_return_type": "unseen",
			"direction": "older",
			"seq_id": "40065",  # 59663
			"limit": "20",
		}
		cursor = None
		items = []
		
		while True:
			if cursor:
				params["cursor"] = cursor

			result = self._call_api(
				f"direct_v2/threads/{thread_id}/", params=params
			)

			thread = result["thread"]
			for item in thread["items"]:
				items.append(item)

			cursor = thread.get("oldest_cursor")
			if not cursor or (max_messages and len(items) >= max_messages):
				break

		if max_messages:
			items = items[:max_messages]


		thread["items"] = items
		return thread


class InstagramMQTT:
	def __init__(self, username, password):
		self.username = username
		self.password = password

		self.settings_file = Path(f"sessions/{self.username}_mqtt.pkl")


	def save_settings(self, data):
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

		self.save_settings(self.settings)

	def on_fbns_auth(self, auth):
		self.settings['fbns_auth'] = auth
		self.settings['fbns_auth_received'] = datetime.now()
		
		self.save_settings(self.settings)

	def on_fbns_token(self, token):
		device_id = self.settings.get('device_id')

		try:
			if self.settings.get('api_settings'):
				self.client = ExtendedClient(
					self.username, self.password,
					settings=self.settings.get('api_settings')
				)
			else:
				self.client = ExtendedClient(
					self.username, self.password,
					on_login=self.on_login_callback
				)

		except (ClientCookieExpiredError, ClientLoginRequiredError) as e:
			self.client = ExtendedClient(
				self.username, self.password,
				device_id=device_id, on_login=self.on_login_callback
			)



		if self.settings.get('fbns_token') == token:
			if "fbns_token_received" in self.settings:
				if self.settings['fbns_token_received'] > datetime.now()-timedelta(hours=24):
					# Do not register token twice in 24 hours
					return

		self.client.register_push(token)

		self.settings['fbns_token'] = token
		self.settings['fbns_token_received'] = datetime.now()
		self.save_settings(self.settings)

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


								with open(self.get_abs_path('settings.json'), 'w') as f:
									json.dump(stgs, f, indent=2)

								self.client.send_direct_message(
									content=msg,
									thread_ids=[msg_thread_id]
								)

							else:
								self.client.send_direct_message(
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

							self.client.send_direct_message(end, thread_ids=[msg_thread_id])

					
				elif notification.pushCategory == "direct_v2_pending":
					msg_thread_id = notification.actionParams['id']
					msg_author = {
						"name": notification.message.split(':')[0],
						"id": notification.sourceUserId
					}


					#thread = self.client.get_direct_thread(thread_id=msg_thread_id, max_messages=1)
					#msg = thread['items'][0]
					#msg_content = msg['text']


					self.client.send_direct_message("Hey! I am now activated, have fun!", thread_ids=[msg_thread_id])


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

	@property
	def Psettings(self):
		with open('settings.json', 'r') as f:
			settings = json.load(f)

		return settings



if __name__ == "__main__":
	loop = asyncio.get_event_loop()

	username, password = env.get("ig-username"), env.get("ig-password")
	app = InstagramMQTT(username or input("Username? "), password or input("Password? "))

	try:
		loop.run_until_complete(app.listener_worker())
	except asyncio.CancelledError:
		pass
