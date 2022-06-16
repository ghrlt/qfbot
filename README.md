# QFBot - Instagram Quoi->Feur bot
[![License: GPL v3](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](http://www.gnu.org/licenses/gpl-3.0)
![](https://komarev.com/ghpvc/?username=ghrlt-qfbot&color=brightgreen&label=Repository%20views)

This bot is THE boss at words play/puns


## Usage
*If you wanna use your own instance of the bot, see [#installation](#installation)*

First, follow [@ghrlt.qfbot](https://instagram.com/ghrlt.qfbot) ;)
Then, if you want to use it in a group, add the bot to it
	- If you are not french, I recommend switching from default lang (fr 🇫🇷) to your<br>
	To do so, you can send `/setlang en` to the bot.<br><br>
	-> If sent in dm, your default language will be modified<br>
	-> If sent in a group, the group chat default language will be modified<br>
	If no language is set for a group, it will either use your set language if one else fr 🇫🇷 


Once the bot is in your group, just chat! When the bot found a message on which he can make a pun, the bot will *instantly* reply with the pun!


## Installation
If using linux, you must install python-dev before! Replace 3.10 with your python version (must be >3.6)
```cmd
sudo apt update
sudo apt install python3.10-dev
```
```cmd
git clone https://github.com/ghrlt/qfbot.git
cd qfbot

pip install -r requirements.txt
```

Once there, you can configure your credentials (else you will be prompted them). Open `.env` file
```env
ig-username=your_ig_username
ig-password=your_ig_password
```

Then you can run the bot!
```cmd
python3 app.py
```
