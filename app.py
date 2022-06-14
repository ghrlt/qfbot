import os
import json
import time
import pickle
import asyncio
import logging

from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta
from instagram_private_api import Client, ClientCookieExpiredError, ClientLoginRequiredError

from fbns_mqtt import fbns_mqtt
from notifications import InstagramNotification


if not "sessions" in os.listdir(): os.mkdir("sessions")
if not "settings.json" in os.listdir(): open('settings.json', 'w').write('{}')

load_dotenv()

logging.basicConfig(
	format='%(asctime)s %(levelname)-8s %(message)s',
	level=logging.DEBUG,
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


	async def listener_worker(self):
		if os.path.exists(self.get_abs_path(self.settings_file)):
			with open(self.get_abs_path(self.settings_file), 'rb') as f:
				self.settings = pickle.load(f)
		else:
			self.settings = {}

		self.client = fbns_mqtt.FBNSMQTTClient()

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
		if self.settings.get('fbns_token') == token:
			if "fbns_token_received" in self.settings:
				if self.settings['fbns_token_received'] > datetime.now()-timedelta(hours=24):
					# Do not register token twice in 24 hours
					return

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

					print(notification)



if __name__ == "__main__":
	loop = asyncio.get_event_loop()

	username, password = os.getenv("ig-username"), os.getenv("ig-password")
	app = InstagramMQTT(username or input("Username? "), password or input("Password? "))

	try:
		loop.run_until_complete(app.listener_worker())
	except asyncio.CancelledError:
		pass
