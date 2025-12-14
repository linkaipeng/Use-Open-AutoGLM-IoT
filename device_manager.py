"""
设备管理模块
处理设备的增删改查操作
"""
import json
import os
from flask import request, jsonify

# 设备配置文件路径
base_dir = os.path.dirname(os.path.abspath(__file__))
DEVICES_CONFIG_FILE = os.path.join(base_dir, 'datas', 'devices.json')


def load_devices():
    """加载设备配置"""
    try:
        if os.path.exists(DEVICES_CONFIG_FILE):
            with open(DEVICES_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"加载设备配置失败: {e}")
        return []


def save_devices(devices):
    """保存设备配置"""
    try:
        with open(DEVICES_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(devices, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存设备配置失败: {e}")
        return False


def get_device_by_id(device_id):
    """根据 ID 获取设备"""
    devices = load_devices()
    for device in devices:
        if device.get('id') == device_id:
            return device
    return None


def register_device_routes(app):
    """注册设备管理相关的路由"""
    
    @app.route('/api/devices', methods=['GET'])
    def get_devices():
        """获取所有设备配置"""
        try:
            devices = load_devices()
            return jsonify({
                "status": "success",
                "devices": devices
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 400

    @app.route('/api/devices', methods=['POST'])
    def add_device():
        """添加新设备"""
        try:
            data = request.get_json()
            devices = load_devices()
            
            # 生成新设备 ID
            if 'id' not in data or not data['id']:
                device_id = f"device_{len(devices) + 1}"
            else:
                device_id = data['id']
            
            # 检查 ID 是否已存在
            if any(d.get('id') == device_id for d in devices):
                return jsonify({
                    "status": "error",
                    "message": f"设备 ID '{device_id}' 已存在"
                }), 400
            
            new_device = {
                "id": device_id,
                "name": data.get('name', '未命名设备'),
                "app": data.get('app', ''),
                "icon": data.get('icon', '📱'),
                "status": data.get('status', '待机'),
                "actions": data.get('actions', [])
            }
            
            devices.append(new_device)
            
            if save_devices(devices):
                return jsonify({
                    "status": "success",
                    "message": "设备添加成功",
                    "device": new_device
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "保存设备配置失败"
                }), 500
                
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 400

    @app.route('/api/devices/<device_id>', methods=['PUT'])
    def update_device(device_id):
        """更新设备配置"""
        try:
            data = request.get_json()
            devices = load_devices()
            
            device_index = None
            for i, device in enumerate(devices):
                if device.get('id') == device_id:
                    device_index = i
                    break
            
            if device_index is None:
                return jsonify({
                    "status": "error",
                    "message": f"设备 ID '{device_id}' 不存在"
                }), 404
            
            # 更新设备信息
            update_data = {
                "name": data.get('name', devices[device_index].get('name')),
                "app": data.get('app', devices[device_index].get('app')),
                "icon": data.get('icon', devices[device_index].get('icon')),
                "status": data.get('status', devices[device_index].get('status', '待机'))
            }
            # 如果提供了 actions，则更新
            if 'actions' in data:
                update_data['actions'] = data.get('actions')
            devices[device_index].update(update_data)
            
            if save_devices(devices):
                return jsonify({
                    "status": "success",
                    "message": "设备更新成功",
                    "device": devices[device_index]
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "保存设备配置失败"
                }), 500
                
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 400

    @app.route('/api/devices/<device_id>', methods=['DELETE'])
    def delete_device(device_id):
        """删除设备"""
        try:
            devices = load_devices()
            devices = [d for d in devices if d.get('id') != device_id]
            
            if save_devices(devices):
                return jsonify({
                    "status": "success",
                    "message": "设备删除成功"
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "保存设备配置失败"
                }), 500
                
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": str(e)
            }), 400

