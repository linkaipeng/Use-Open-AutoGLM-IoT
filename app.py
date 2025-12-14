from flask import Flask, request, jsonify, Response, stream_with_context, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
import json
import sys
import subprocess
import os
import base64
import io
import threading
import re
import requests

# 加载环境变量
load_dotenv()

# 导入小米音箱语音接收模块
try:
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'mi'))
    from account import AccountManager, MiAccount
    from mina import MiNA
    from voice import VoiceReceiver, VoiceMessage
    MI_MODULE_AVAILABLE = True
except ImportError as e:
    print(f"⚠️ 小米音箱模块导入失败: {e}")
    MI_MODULE_AVAILABLE = False
    VoiceReceiver = None
    VoiceMessage = None

app = Flask(__name__)
CORS(app)  # 允许跨域请求，这样 HTML 可以调用后端

# 从环境变量读取配置
FLASK_HOST = os.getenv('FLASK_HOST', '0.0.0.0')
FLASK_PORT = int(os.getenv('FLASK_PORT', 5001))
FLASK_DEBUG = os.getenv('FLASK_DEBUG', 'True').lower() == 'true'

ZHIPU_API_KEY = os.getenv('ZHIPU_API_KEY')
ZHIPU_API_BASE_URL = os.getenv('ZHIPU_API_BASE_URL', 'https://open.bigmodel.cn/api/paas/v4')
ZHIPU_MODEL = os.getenv('ZHIPU_MODEL', 'autoglm-phone')

# 小米配置仅从 mi/config.py 读取，不使用环境变量

# 配置文件路径
base_dir = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(base_dir, os.getenv('ICONS_DIR', 'icons'))
MI_CONFIG_FILE = os.path.join(base_dir, 'mi', 'config.py')
DATAS_DIR = os.path.join(base_dir, 'datas')

# 全局变量：语音接收器
voice_receiver = None
voice_receiver_lock = threading.Lock()

# 全局变量：日志队列（用于推送到前端）
log_queue = []
log_queue_lock = threading.Lock()
log_listeners = set()  # SSE 连接的监听器集合

def add_log_to_queue(log_data):
    """添加日志到队列并推送给所有监听器"""
    global log_queue, log_listeners
    
    with log_queue_lock:
        # 添加到队列（保留最近100条）
        log_queue.append(log_data)
        if len(log_queue) > 100:
            log_queue.pop(0)
        
        # 推送给所有 SSE 监听器
        disconnected_listeners = []
        for listener in log_listeners.copy():
            try:
                listener.put(log_data)
            except Exception:
                disconnected_listeners.append(listener)
        
        # 移除断开的连接
        for listener in disconnected_listeners:
            log_listeners.discard(listener)

# 导入设备管理和定时任务模块
from device_manager import register_device_routes, get_device_by_id
from scheduler import register_schedule_routes, start_scheduler

def parse_voice_command_with_ai(voice_text):
    """使用 AI 解析语音命令，智能匹配到设备和操作"""
    import time
    
    # 加载设备配置
    from device_manager import load_devices
    devices = load_devices()
    
    # 构建设备信息的描述
    devices_info = []
    for device in devices:
        actions_list = []
        for action in device.get('actions', []):
            actions_list.append({
                "id": action.get('id'),
                "name": action.get('name'),
                "description": action.get('command', '').replace('{app}', device.get('app', ''))
            })
        
        devices_info.append({
            "id": device.get('id'),
            "name": device.get('name'),
            "app": device.get('app'),
            "actions": actions_list
        })
    
    # 构建提示词
    prompt = f"""你是一个智能家居助手。用户说了一句话，请从以下设备列表中找出最匹配的设备和操作。

用户说的话："{voice_text}"

可用的设备和操作：
{json.dumps(devices_info, ensure_ascii=False, indent=2)}

请分析用户的意图，返回最匹配的设备ID和操作ID。
如果无法匹配到任何设备或操作，返回 null。

请只返回 JSON 格式的结果，格式如下：
{{
    "device_id": "设备ID",
    "action_id": "操作ID",
    "confidence": "匹配置信度(0-1)",
    "reason": "匹配原因"
}}

或者如果无法匹配：
{{
    "device_id": null,
    "action_id": null,
    "reason": "无法匹配的原因"
}}

只返回 JSON，不要有其他内容。"""
    
    try:
        # 调用智谱 API
        if not ZHIPU_API_KEY:
            print("❌ 未配置 ZHIPU_API_KEY")
            return None
            
        api_url = f"{ZHIPU_API_BASE_URL}/chat/completions"
        
        headers = {
            "Authorization": f"Bearer {ZHIPU_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": "glm-4-flash",
            "messages": [
                {
                    "role": "user",
                    "content": prompt
                }
            ],
            "temperature": 0.1,  # 降低温度以获得更确定的结果
            "max_tokens": 500
        }
        
        print(f"🤖 正在使用 AI 匹配语音命令: {voice_text}")
        response = requests.post(api_url, headers=headers, json=data, timeout=10)
        
        if response.status_code == 200:
            result = response.json()
            content = result.get('choices', [{}])[0].get('message', {}).get('content', '').strip()
            
            print(f"🤖 AI 返回结果: {content}")
            
            # 解析 JSON 结果
            # 移除可能的 markdown 代码块标记
            content = content.replace('```json', '').replace('```', '').strip()
            match_result = json.loads(content)
            
            if match_result.get('device_id') and match_result.get('action_id'):
                # 获取设备和操作的详细信息
                device = get_device_by_id(match_result['device_id'])
                if device:
                    action = None
                    for a in device.get('actions', []):
                        if a.get('id') == match_result['action_id']:
                            action = a
                            break
                    
                    if action:
                        print(f"✅ AI 匹配成功: {device.get('name')} - {action.get('name')} (置信度: {match_result.get('confidence', 'N/A')})")
                        return {
                            "device_id": match_result['device_id'],
                            "action_id": match_result['action_id'],
                            "device_name": device.get('name'),
                            "action_name": action.get('name'),
                            "confidence": match_result.get('confidence', 1.0),
                            "reason": match_result.get('reason', '')
                        }
            
            print(f"⚠️ AI 未能匹配到有效的设备操作: {match_result.get('reason', '未知原因')}")
            return None
            
        else:
            print(f"❌ AI API 调用失败: {response.status_code} - {response.text}")
            return None
            
    except Exception as e:
        print(f"❌ AI 匹配过程出错: {e}")
        import traceback
        traceback.print_exc()
        return None

@app.route('/')
def index():
    return jsonify({"message": "Flow Home 智能家居控制服务运行正常！"})

@app.route('/api/icons/<filename>')
def get_icon(filename):
    """获取图标文件"""
    try:
        return send_from_directory(ICONS_DIR, filename)
    except Exception as e:
        return jsonify({"error": str(e)}), 404

@app.route('/api/icons', methods=['GET'])
def list_icons():
    """列出所有可用的图标文件"""
    try:
        icons = []
        if os.path.exists(ICONS_DIR):
            for filename in os.listdir(ICONS_DIR):
                if os.path.isfile(os.path.join(ICONS_DIR, filename)):
                    icons.append(filename)
        return jsonify({
            "status": "success",
            "icons": sorted(icons)
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 400

@app.route('/api/phone-screen', methods=['GET'])
def get_phone_screen():
    """获取手机屏幕截图"""
    try:
        # 使用 adb 获取屏幕截图
        result = subprocess.run(
            ['adb', 'exec-out', 'screencap', '-p'],
            capture_output=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return jsonify({
                "status": "error",
                "message": "获取屏幕截图失败",
                "error": result.stderr.decode('utf-8', errors='ignore')
            }), 400
        
        # 将截图转换为 base64
        screenshot_base64 = base64.b64encode(result.stdout).decode('utf-8')
        
        return jsonify({
            "status": "success",
            "screenshot": f"data:image/png;base64,{screenshot_base64}"
        })
        
    except FileNotFoundError:
        return jsonify({
            "status": "error",
            "message": "未找到 ADB 命令，请确保已安装 Android SDK Platform Tools",
            "error": "adb command not found"
        }), 400
    except subprocess.TimeoutExpired:
        return jsonify({
            "status": "error",
            "message": "获取屏幕截图超时",
            "error": "Command timeout"
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "message": "获取屏幕截图时出错",
            "error": str(e)
        }), 400

@app.route('/api/check-adb-device', methods=['GET'])
def check_adb_device():
    """检测 ADB 设备连接状态"""
    try:
        # 执行 adb devices 命令
        result = subprocess.run(
            ['adb', 'devices'],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode != 0:
            return jsonify({
                "status": "error",
                "connected": False,
                "message": "ADB 命令执行失败",
                "error": result.stderr
            }), 400
        
        # 解析输出
        lines = result.stdout.strip().split('\n')
        devices = []
        
        # 跳过第一行 "List of devices attached"
        for line in lines[1:]:
            if line.strip() and '\t' in line:
                parts = line.strip().split('\t')
                if len(parts) >= 2:
                    device_id = parts[0]
                    status = parts[1]
                    devices.append({
                        "device_id": device_id,
                        "status": status
                    })
        
        # 检查是否有已连接的设备（状态为 device）
        connected_devices = [d for d in devices if d['status'] == 'device']
        is_connected = len(connected_devices) > 0
        
        return jsonify({
            "status": "success",
            "connected": is_connected,
            "device_count": len(connected_devices),
            "devices": devices,
            "message": f"检测到 {len(connected_devices)} 个已连接设备" if is_connected else "未检测到已连接的设备"
        })
        
    except FileNotFoundError:
        return jsonify({
            "status": "error",
            "connected": False,
            "message": "未找到 ADB 命令，请确保已安装 Android SDK Platform Tools",
            "error": "adb command not found"
        }), 400
    except subprocess.TimeoutExpired:
        return jsonify({
            "status": "error",
            "connected": False,
            "message": "ADB 命令执行超时",
            "error": "Command timeout"
        }), 400
    except Exception as e:
        return jsonify({
            "status": "error",
            "connected": False,
            "message": "检测设备时出错",
            "error": str(e)
        }), 400

# 设备管理路由已移至 device_manager.py

def execute_device_action_internal(device_id, action_id):
    """内部执行设备操作的函数（不返回流式响应）"""
    try:
        device = get_device_by_id(device_id)
        if not device:
            return {"status": "error", "message": f"设备 ID {device_id} 不存在"}
        
        # 获取设备应用名称
        app_name = device.get('app', '')
        command_text = ''
        action_name = '默认操作'
        
        # 如果指定了 action_id，从 actions 中查找对应的命令
        if action_id and device.get('actions'):
            for action in device.get('actions', []):
                if action.get('id') == action_id:
                    action_command = action.get('command', '')
                    # 将 action.command 中的 {app} 替换为实际的应用名称
                    if action_command and app_name:
                        command_text = action_command.replace('{app}', app_name)
                    else:
                        command_text = action_command
                    action_name = action.get('name', action_id)
                    break
        
        if not command_text:
            return {"status": "error", "message": "未找到对应的操作"}
        
        # 检查必要的环境变量
        if not ZHIPU_API_KEY:
            return jsonify({
                "status": "error",
                "message": "未配置 ZHIPU_API_KEY"
            }), 500
        
        # 构建命令
        cmd = [
            sys.executable,
            "/Users/linkaipeng/Documents/work/ai/demo/Open-AutoGLM/Open-AutoGLM/main.py",
            "--base-url", ZHIPU_API_BASE_URL,
            "--model", ZHIPU_MODEL,
            "--apikey", ZHIPU_API_KEY,
            command_text
        ]
        
        # 执行命令（非阻塞）
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env = os.environ.copy()
        env['PYTHONUNBUFFERED'] = '1'
        
        process = subprocess.Popen(
            cmd,
            cwd=current_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env
        )
        
        # 添加开始执行的消息
        import time
        add_log_to_queue({
            'type': 'start',
            'message': f'🚀 开始执行: {device.get("name")} - {action_name}',
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
            'final_command': command_text
        })
        
        # 在后台线程中等待完成并捕获输出
        def wait_process():
            import time
            try:
                # 读取输出
                for line in process.stdout:
                    if line:
                        line_stripped = line.rstrip()
                        print(line_stripped)
                        # 实时推送输出到日志
                        add_log_to_queue({
                            'type': 'output',
                            'line': line_stripped,
                            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                        })
                
                process.wait()
                
                # 添加完成消息
                if process.returncode == 0:
                    add_log_to_queue({
                        'type': 'success',
                        'message': f'✅ 语音触发的设备操作完成: {device.get("name")} - {action_name}',
                        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    })
                else:
                    add_log_to_queue({
                        'type': 'error',
                        'message': f'❌ 语音触发的设备操作失败: {device.get("name")} - {action_name} (返回码: {process.returncode})',
                        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                    })
            except Exception as e:
                add_log_to_queue({
                    'type': 'error',
                    'message': f'❌ 执行过程出错: {str(e)}',
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                })
        
        threading.Thread(target=wait_process, daemon=True).start()
        
        return {
            "status": "success",
            "message": f"已触发: {device.get('name')} - {action_name}",
            "device": device.get('name'),
            "action": action_name
        }
        
    except Exception as e:
        return {"status": "error", "message": f"执行出错: {str(e)}"}

def on_voice_message(message):
    """收到语音消息时的回调函数"""
    if not MI_MODULE_AVAILABLE:
        print("⚠️ MI_MODULE_AVAILABLE 为 False，无法处理语音消息")
        return
    
    import time
    timestamp = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
    
    voice_text = message.text
    print(f"🎤 收到语音: {voice_text}")
    
    # 添加语音消息到日志
    add_log_to_queue({
        'type': 'voice',
        'message': f'🎤 收到语音: {voice_text}',
        'timestamp': timestamp,
        'voice_text': voice_text
    })
    
    # 使用 AI 解析语音命令
    command_match = parse_voice_command_with_ai(voice_text)
    
    if command_match:
        device_name = command_match['device_name']
        action_name = command_match['action_name']
        print(f"✅ 匹配到设备: {device_name} - {action_name}")
        
        # 添加匹配信息到日志
        add_log_to_queue({
            'type': 'match',
            'message': f'✅ 匹配到设备: {device_name} - {action_name}',
            'timestamp': timestamp,
            'device_name': device_name,
            'action_name': action_name
        })
        
        # 执行设备操作
        result = execute_device_action_internal(
            command_match['device_id'],
            command_match['action_id']
        )
        
        result_msg = result.get('message', '未知')
        print(f"📱 执行结果: {result_msg}")
        
        # 添加执行结果到日志
        if result.get('status') == 'success':
            add_log_to_queue({
                'type': 'success',
                'message': f'📱 {result_msg}',
                'timestamp': timestamp
            })
        else:
            add_log_to_queue({
                'type': 'error',
                'message': f'❌ 执行失败: {result_msg}',
                'timestamp': timestamp
            })
    else:
        print(f"⚠️ 未匹配到设备操作: {voice_text}")
        # 添加未匹配信息到日志
        add_log_to_queue({
            'type': 'warning',
            'message': f'⚠️ 未匹配到设备操作: {voice_text}',
            'timestamp': timestamp
        })

@app.route('/api/devices/<device_id>/execute', methods=['POST'])
def execute_device(device_id):
    """执行设备命令（流式输出）"""
    def generate():
        try:
            device = get_device_by_id(device_id)
            if not device:
                yield f"data: {json.dumps({'type': 'error', 'message': f'设备 ID {device_id} 不存在'}, ensure_ascii=False)}\n\n"
                return
            
            # 获取请求参数
            request_data = request.get_json() or {}
            action_id = request_data.get('action_id')
            
            # 确定要执行的命令
            command_text = ''
            action_name = '默认操作'
            final_command = ''
            
            # 获取设备应用名称
            app_name = device.get('app', '')
            
            # 如果指定了 action_id，从 actions 中查找对应的命令
            if action_id and device.get('actions'):
                for action in device.get('actions', []):
                    if action.get('id') == action_id:
                        action_command = action.get('command', '')
                        # 将 action.command 中的 {app} 替换为实际的应用名称
                        if action_command and app_name:
                            command_text = action_command.replace('{app}', app_name)
                        else:
                            command_text = action_command
                        final_command = command_text
                        action_name = action.get('name', action_id)
                        break
            else:
                # 如果没有指定 action_id，返回错误
                yield f"data: {json.dumps({'type': 'error', 'message': '未指定操作'}, ensure_ascii=False)}\n\n"
                return
            
            # 检查必要的环境变量
            if not ZHIPU_API_KEY:
                print(f"❌ 未配置 ZHIPU_API_KEY")
                return {
                    "status": "error",
                    "message": "未配置 ZHIPU_API_KEY"
                }
            
            # 构建命令
            cmd = [
                sys.executable,  # 使用当前 Python 解释器
                "/Users/linkaipeng/Documents/work/ai/demo/Open-AutoGLM/Open-AutoGLM/main.py",
                "--base-url", ZHIPU_API_BASE_URL,
                "--model", ZHIPU_MODEL,
                "--apikey", ZHIPU_API_KEY,
                command_text
            ]
            
            # 获取当前工作目录（Flask app 所在目录）
            current_dir = os.path.dirname(os.path.abspath(__file__))
            
            # 发送开始消息
            device_name = device.get('name', '未知设备')
            yield f"data: {json.dumps({'type': 'start', 'message': f'开始执行: {device_name} - {action_name}', 'command': ' '.join(cmd), 'final_command': final_command}, ensure_ascii=False)}\n\n"
            
            # 设置环境变量，确保 Python 输出无缓冲
            env = os.environ.copy()
            env['PYTHONUNBUFFERED'] = '1'
            
            # 使用 Popen 实时读取输出
            process = subprocess.Popen(
                cmd,
                cwd=current_dir,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0,  # 无缓冲
                universal_newlines=True,
                env=env
            )
            
            # 实时读取输出
            try:
                while True:
                    line = process.stdout.readline()
                    if not line and process.poll() is not None:
                        break
                    if line:
                        # 发送每一行输出
                        yield f"data: {json.dumps({'type': 'output', 'line': line.rstrip()}, ensure_ascii=False)}\n\n"
            finally:
                # 确保进程结束
                if process.poll() is None:
                    process.wait()
            
            # 发送结束消息
            if process.returncode == 0:
                yield f"data: {json.dumps({'type': 'end', 'status': 'success', 'message': '命令执行完成', 'returncode': process.returncode}, ensure_ascii=False)}\n\n"
            else:
                yield f"data: {json.dumps({'type': 'end', 'status': 'error', 'message': '命令执行失败', 'returncode': process.returncode}, ensure_ascii=False)}\n\n"
                
        except FileNotFoundError:
            file_path = cmd[1] if len(cmd) > 1 else "未知"
            error_msg = f"文件路径: {file_path}"
            yield f"data: {json.dumps({'type': 'error', 'message': '找不到 main.py 文件', 'error': error_msg}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'message': '执行出错', 'error': str(e)}, ensure_ascii=False)}\n\n"
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

def _start_voice_receiver_internal():
    """内部启动语音接收器函数（不返回HTTP响应）"""
    global voice_receiver
    
    if not MI_MODULE_AVAILABLE:
        print("⚠️ 小米音箱模块未安装或配置错误，跳过语音接收器启动")
        return False
    
    with voice_receiver_lock:
        if voice_receiver and voice_receiver.is_running:
            print("ℹ️ 语音接收器已在运行中")
            return True
        
        try:
            # 检查配置文件是否存在
            if not os.path.exists(MI_CONFIG_FILE):
                print("⚠️ 未找到小米音箱配置文件，跳过语音接收器启动")
                return False
            
            # 导入配置
            import importlib.util
            import time
            spec = importlib.util.spec_from_file_location("mi_config", MI_CONFIG_FILE)
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)
            
            # 检查配置
            if not hasattr(config, "USER_ID") or config.USER_ID == "你的小米ID":
                print("⚠️ 未配置 USER_ID，跳过语音接收器启动")
                return False
            
            if not hasattr(config, "DEVICE_NAME") or config.DEVICE_NAME == "你的音箱名称":
                print("⚠️ 未配置 DEVICE_NAME，跳过语音接收器启动")
                return False
            
            # 创建账号管理器
            account_manager = AccountManager()
            
            # 创建账号对象
            account = MiAccount(
                sid="micoapi",
                device_id=f"android_{os.urandom(5).hex()}",
                user_id=config.USER_ID,
                password=getattr(config, "PASSWORD", None),
                pass_token=getattr(config, "PASS_TOKEN", None),
                did=config.DEVICE_NAME,
            )
            
            # 登录
            print(f"🔐 正在登录小米账号...")
            add_log_to_queue({
                'type': 'info',
                'message': f'🔐 正在登录小米账号...',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            account = account_manager.get_account(account)
            if not account:
                error_msg = "登录失败，请检查账号信息"
                print(f"❌ {error_msg}")
                add_log_to_queue({
                    'type': 'error',
                    'message': f'❌ {error_msg}',
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                })
                return False
            
            print(f"✅ 登录成功")
            add_log_to_queue({
                'type': 'success',
                'message': f'✅ 小米账号登录成功',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            # 创建 MiNA 实例
            print(f"📱 创建 MiNA 实例...")
            mina = MiNA(account)
            print(f"✅ MiNA 实例创建成功")
            
            # 创建语音接收器
            voice_receiver = VoiceReceiver(mina)
            
            # 添加启动日志
            add_log_to_queue({
                'type': 'info',
                'message': f'🔧 正在启动语音接收器...',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            # 开始监听
            poll_interval = getattr(config, "POLL_INTERVAL", 1000)
            print(f"📡 启动语音接收器，轮询间隔: {poll_interval}ms")
            print(f"📡 设备名称: {config.DEVICE_NAME}")
            print(f"📡 用户ID: {config.USER_ID}")
            
            # 添加调试信息到日志
            add_log_to_queue({
                'type': 'info',
                'message': f'📡 配置信息 - 设备: {config.DEVICE_NAME}, 轮询间隔: {poll_interval}ms',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            voice_receiver.start(
                callback=on_voice_message,
                interval=poll_interval,
                only_new=True,
            )
            
            # 添加启动成功日志
            add_log_to_queue({
                'type': 'success',
                'message': f'✅ 语音接收器已启动，正在监听设备: {config.DEVICE_NAME}',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            print(f"✅ 语音接收器启动成功")
            return True
            
        except Exception as e:
            print(f"❌ 启动语音接收器失败: {str(e)}")
            import traceback
            traceback.print_exc()
            return False

@app.route('/api/voice/start', methods=['POST'])
def start_voice_receiver():
    """启动语音接收器（API端点）"""
    global voice_receiver
    
    if not MI_MODULE_AVAILABLE:
        return jsonify({
            "status": "error",
            "message": "小米音箱模块未安装或配置错误"
        }), 400
    
    with voice_receiver_lock:
        if voice_receiver and voice_receiver.is_running:
            return jsonify({
                "status": "error",
                "message": "语音接收器已在运行中"
            }), 400
        
        try:
            # 检查配置文件是否存在
            if not os.path.exists(MI_CONFIG_FILE):
                print("⚠️ 未找到小米音箱配置文件，跳过语音接收器启动")
                return False
            
            # 导入配置
            import importlib.util
            import time
            spec = importlib.util.spec_from_file_location("mi_config", MI_CONFIG_FILE)
            config = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(config)
            
            # 检查配置
            if not hasattr(config, "USER_ID") or config.USER_ID == "你的小米ID":
                print("⚠️ 未配置 USER_ID，跳过语音接收器启动")
                return False
            
            if not hasattr(config, "DEVICE_NAME") or config.DEVICE_NAME == "你的音箱名称":
                print("⚠️ 未配置 DEVICE_NAME，跳过语音接收器启动")
                return False
            
            # 创建账号管理器
            account_manager = AccountManager()
            
            # 创建账号对象
            account = MiAccount(
                sid="micoapi",
                device_id=f"android_{os.urandom(5).hex()}",
                user_id=config.USER_ID,
                password=getattr(config, "PASSWORD", None),
                pass_token=getattr(config, "PASS_TOKEN", None),
                did=config.DEVICE_NAME,
            )
            
            # 登录
            print(f"🔐 正在登录小米账号...")
            add_log_to_queue({
                'type': 'info',
                'message': f'🔐 正在登录小米账号...',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            account = account_manager.get_account(account)
            if not account:
                error_msg = "登录失败，请检查账号信息"
                print(f"❌ {error_msg}")
                add_log_to_queue({
                    'type': 'error',
                    'message': f'❌ {error_msg}',
                    'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
                })
                return False
            
            print(f"✅ 登录成功")
            add_log_to_queue({
                'type': 'success',
                'message': f'✅ 小米账号登录成功',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            # 创建 MiNA 实例
            print(f"📱 创建 MiNA 实例...")
            mina = MiNA(account)
            print(f"✅ MiNA 实例创建成功")
            
            # 创建语音接收器
            voice_receiver = VoiceReceiver(mina)
            
            # 添加启动日志
            add_log_to_queue({
                'type': 'info',
                'message': f'🔧 正在启动语音接收器...',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            # 开始监听
            poll_interval = getattr(config, "POLL_INTERVAL", 1000)
            print(f"📡 启动语音接收器，轮询间隔: {poll_interval}ms")
            print(f"📡 设备名称: {config.DEVICE_NAME}")
            print(f"📡 用户ID: {config.USER_ID}")
            
            # 添加调试信息到日志
            add_log_to_queue({
                'type': 'info',
                'message': f'📡 配置信息 - 设备: {config.DEVICE_NAME}, 轮询间隔: {poll_interval}ms',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            voice_receiver.start(
                callback=on_voice_message,
                interval=poll_interval,
                only_new=True,
            )
            
            # 添加启动成功日志
            add_log_to_queue({
                'type': 'success',
                'message': f'✅ 语音接收器已启动，正在监听设备: {config.DEVICE_NAME}',
                'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
            })
            
            return jsonify({
                "status": "success",
                "message": "语音接收器已启动"
            })
            
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"启动语音接收器失败: {str(e)}"
            }), 500

@app.route('/api/voice/stop', methods=['POST'])
def stop_voice_receiver():
    """停止语音接收器"""
    global voice_receiver
    
    with voice_receiver_lock:
        if not voice_receiver or not voice_receiver.is_running:
            return jsonify({
                "status": "error",
                "message": "语音接收器未运行"
            }), 400
        
        try:
            voice_receiver.stop()
            return jsonify({
                "status": "success",
                "message": "语音接收器已停止"
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"停止语音接收器失败: {str(e)}"
            }), 500

@app.route('/api/voice/status', methods=['GET'])
def get_voice_status():
    """获取语音接收器状态"""
    global voice_receiver
    
    if not MI_MODULE_AVAILABLE:
        return jsonify({
            "status": "success",
            "running": False,
            "available": False,
            "message": "小米音箱模块未安装"
        })
    
    with voice_receiver_lock:
        is_running = voice_receiver is not None and voice_receiver.is_running
        
        return jsonify({
            "status": "success",
            "running": is_running,
            "available": True,
            "message": "语音接收器运行中" if is_running else "语音接收器未运行"
        })

@app.route('/api/logs/stream', methods=['GET'])
def stream_logs():
    """流式推送日志（Server-Sent Events）"""
    import queue
    import time
    
    def generate():
        # 创建一个队列用于接收日志
        log_queue_local = queue.Queue()
        
        # 添加到监听器集合
        with log_queue_lock:
            log_listeners.add(log_queue_local)
        
        try:
            # 发送初始消息
            yield f"data: {json.dumps({'type': 'connected', 'message': '日志流已连接'}, ensure_ascii=False)}\n\n"
            
            # 发送历史日志（最近20条）
            with log_queue_lock:
                recent_logs = log_queue[-20:] if len(log_queue) > 20 else log_queue
                for log_data in recent_logs:
                    yield f"data: {json.dumps(log_data, ensure_ascii=False)}\n\n"
            
            # 持续监听新日志
            while True:
                try:
                    # 等待新日志，超时1秒
                    log_data = log_queue_local.get(timeout=1)
                    yield f"data: {json.dumps(log_data, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    # 发送心跳保持连接
                    yield f"data: {json.dumps({'type': 'heartbeat', 'timestamp': time.time()}, ensure_ascii=False)}\n\n"
        finally:
            # 移除监听器
            with log_queue_lock:
                log_listeners.discard(log_queue_local)
    
    return Response(stream_with_context(generate()), mimetype='text/event-stream')

# ==================== 注册模块路由 ====================

# 注册设备管理路由
register_device_routes(app)

# 设置定时任务模块的回调函数
import scheduler
scheduler.execute_device_action_callback = execute_device_action_internal
scheduler.add_log_to_queue_callback = add_log_to_queue
scheduler.get_device_by_id_callback = get_device_by_id

# 注册定时任务路由
register_schedule_routes(app)

if __name__ == '__main__':
    print("=" * 60)
    print("启动 IoT 智能家居控制系统")
    print("=" * 60)
    print(f"📍 访问地址: http://{FLASK_HOST}:{FLASK_PORT}")
    print(f"🐛 调试模式: {'开启' if FLASK_DEBUG else '关闭'}")
    print()
    
    # 检查必要的环境变量
    if not ZHIPU_API_KEY:
        print("⚠️  警告: 未配置 ZHIPU_API_KEY，AI 匹配功能将不可用")
    else:
        print(f"✅ 智谱 AI: 已配置 (模型: {ZHIPU_MODEL})")
    
    if MI_MODULE_AVAILABLE:
        print("✅ 小米音箱模块: 已加载")
        # 检查配置文件是否存在
        if os.path.exists(MI_CONFIG_FILE):
            try:
                import importlib.util
                spec = importlib.util.spec_from_file_location("mi_config", MI_CONFIG_FILE)
                config = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(config)
                
                user_id = getattr(config, "USER_ID", None)
                device_name = getattr(config, "DEVICE_NAME", None)
                
                if user_id and device_name and user_id != "你的小米ID" and device_name != "你的音箱名称":
                    print(f"   配置文件: mi/config.py")
                    print(f"   用户ID: {user_id}")
                    print(f"   设备: {device_name}")
                    # 自动启动语音接收器
                    print("🚀 正在自动启动语音接收器...")
                    _start_voice_receiver_internal()
                else:
                    print("⚠️  警告: mi/config.py 中未正确配置账号信息，语音功能将不可用")
            except Exception as e:
                print(f"⚠️  警告: 读取 mi/config.py 失败: {e}")
        else:
            print("⚠️  警告: 未找到 mi/config.py 配置文件，语音功能将不可用")
    else:
        print("⚠️  小米音箱模块: 未加载，语音功能不可用")
    
    print()
    # 启动定时任务调度器
    print("🚀 正在启动定时任务调度器...")
    start_scheduler()
    
    print()
    print("=" * 60)
    print("服务器启动中...")
    print("=" * 60)
    
    app.run(debug=FLASK_DEBUG, host=FLASK_HOST, port=FLASK_PORT)
