"""
定时任务调度模块
处理定时任务的增删改查和调度执行
"""
import json
import os
import threading
import schedule
import time as time_module
import uuid
from flask import request, jsonify

# 定时任务配置文件路径
base_dir = os.path.dirname(os.path.abspath(__file__))
SCHEDULES_CONFIG_FILE = os.path.join(base_dir, 'datas', 'schedules.json')

# 全局调度器线程
scheduler_thread = None
scheduler_running = False

# 需要从 app.py 导入的函数（通过回调方式注入）
execute_device_action_callback = None
add_log_to_queue_callback = None
get_device_by_id_callback = None


def load_schedules():
    """加载定时任务配置"""
    try:
        if os.path.exists(SCHEDULES_CONFIG_FILE):
            with open(SCHEDULES_CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return []
    except Exception as e:
        print(f"加载定时任务配置失败: {e}")
        return []


def save_schedules(schedules):
    """保存定时任务配置"""
    try:
        with open(SCHEDULES_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(schedules, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存定时任务配置失败: {e}")
        return False


def get_schedule_by_id(schedule_id):
    """根据 ID 获取定时任务"""
    schedules = load_schedules()
    for schedule in schedules:
        if schedule.get('id') == schedule_id:
            return schedule
    return None


def execute_scheduled_task(schedule_data):
    """执行定时任务"""
    try:
        device_id = schedule_data.get('device_id')
        action_id = schedule_data.get('action_id')
        schedule_name = schedule_data.get('name', '未命名任务')
        
        print(f"⏰ 定时任务触发: {schedule_name}")
        
        if add_log_to_queue_callback:
            add_log_to_queue_callback({
                'type': 'info',
                'message': f'⏰ 定时任务触发: {schedule_name}',
                'timestamp': time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime())
            })
        
        # 执行设备操作
        if execute_device_action_callback:
            result = execute_device_action_callback(device_id, action_id)
            
            if result.get('status') == 'success':
                print(f"✅ 定时任务执行成功: {schedule_name}")
            else:
                print(f"❌ 定时任务执行失败: {schedule_name}")
        else:
            print("⚠️ 设备操作回调函数未设置")
            
    except Exception as e:
        print(f"❌ 定时任务执行出错: {e}")
        import traceback
        traceback.print_exc()


def setup_schedule_job(schedule_data):
    """设置单个定时任务"""
    if not schedule_data.get('enabled'):
        return
    
    time_str = schedule_data.get('time')  # 格式: "HH:MM"
    repeat_type = schedule_data.get('repeat', 'once')
    weekdays = schedule_data.get('weekdays', [])
    
    if repeat_type == 'once':
        # 仅一次
        schedule.every().day.at(time_str).do(
            lambda sd=schedule_data: execute_scheduled_task(sd)
        ).tag(schedule_data.get('id'))
        
    elif repeat_type == 'daily':
        # 每天
        schedule.every().day.at(time_str).do(
            lambda sd=schedule_data: execute_scheduled_task(sd)
        ).tag(schedule_data.get('id'))
        
    elif repeat_type == 'weekdays':
        # 工作日
        for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday']:
            getattr(schedule.every(), day).at(time_str).do(
                lambda sd=schedule_data: execute_scheduled_task(sd)
            ).tag(schedule_data.get('id'))
            
    elif repeat_type == 'weekends':
        # 周末
        for day in ['saturday', 'sunday']:
            getattr(schedule.every(), day).at(time_str).do(
                lambda sd=schedule_data: execute_scheduled_task(sd)
            ).tag(schedule_data.get('id'))
            
    elif repeat_type == 'weekly' and weekdays:
        # 每周指定日期
        day_map = {
            0: 'sunday',
            1: 'monday',
            2: 'tuesday',
            3: 'wednesday',
            4: 'thursday',
            5: 'friday',
            6: 'saturday'
        }
        for weekday in weekdays:
            day_name = day_map.get(weekday)
            if day_name:
                getattr(schedule.every(), day_name).at(time_str).do(
                    lambda sd=schedule_data: execute_scheduled_task(sd)
                ).tag(schedule_data.get('id'))


def load_and_setup_schedules():
    """加载并设置所有定时任务"""
    try:
        # 清除所有现有任务
        schedule.clear()
        
        # 加载任务配置
        schedules = load_schedules()
        
        print(f"📅 加载定时任务: {len(schedules)} 个")
        
        for schedule_data in schedules:
            if schedule_data.get('enabled'):
                setup_schedule_job(schedule_data)
                print(f"  ✓ {schedule_data.get('name')} - {schedule_data.get('time')}")
            else:
                print(f"  ⊗ {schedule_data.get('name')} - 已禁用")
                
    except Exception as e:
        print(f"❌ 加载定时任务失败: {e}")
        import traceback
        traceback.print_exc()


def reload_scheduler():
    """重新加载调度器"""
    load_and_setup_schedules()


def run_scheduler():
    """运行调度器（在后台线程中）"""
    global scheduler_running
    scheduler_running = True
    
    print("🕐 定时任务调度器已启动")
    
    while scheduler_running:
        try:
            schedule.run_pending()
            time_module.sleep(1)
        except Exception as e:
            print(f"❌ 调度器运行出错: {e}")
            time_module.sleep(5)


def start_scheduler():
    """启动调度器线程"""
    global scheduler_thread
    
    if scheduler_thread and scheduler_thread.is_alive():
        print("⚠️ 调度器已在运行中")
        return
    
    # 加载任务
    load_and_setup_schedules()
    
    # 启动后台线程
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()


def stop_scheduler():
    """停止调度器"""
    global scheduler_running
    scheduler_running = False
    print("🛑 定时任务调度器已停止")


def register_schedule_routes(app):
    """注册定时任务相关的路由"""
    
    @app.route('/api/schedules', methods=['GET'])
    def get_schedules():
        """获取所有定时任务"""
        try:
            schedules = load_schedules()
            
            # 补充设备和操作名称
            if get_device_by_id_callback:
                for schedule_item in schedules:
                    device = get_device_by_id_callback(schedule_item.get('device_id'))
                    if device:
                        schedule_item['device_name'] = device.get('name')
                        schedule_item['device_app'] = device.get('app')
                        
                        # 查找操作名称
                        for action in device.get('actions', []):
                            if action.get('id') == schedule_item.get('action_id'):
                                schedule_item['action_name'] = action.get('name')
                                break
            
            return jsonify({
                "status": "success",
                "schedules": schedules
            })
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"获取定时任务失败: {str(e)}"
            }), 500

    @app.route('/api/schedules', methods=['POST'])
    def create_schedule():
        """创建定时任务"""
        try:
            data = request.json
            schedules = load_schedules()
            
            # 生成新的 ID
            new_schedule = {
                "id": str(uuid.uuid4())[:8],
                "name": data.get('name'),
                "device_id": data.get('device_id'),
                "action_id": data.get('action_id'),
                "time": data.get('time'),
                "repeat": data.get('repeat', 'once'),
                "weekdays": data.get('weekdays', []),
                "enabled": data.get('enabled', True),
                "created_at": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime())
            }
            
            schedules.append(new_schedule)
            
            if save_schedules(schedules):
                # 重新加载调度器
                reload_scheduler()
                return jsonify({
                    "status": "success",
                    "message": "定时任务创建成功",
                    "schedule": new_schedule
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "保存定时任务失败"
                }), 500
                
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"创建定时任务失败: {str(e)}"
            }), 500

    @app.route('/api/schedules/<schedule_id>', methods=['PUT'])
    def update_schedule(schedule_id):
        """更新定时任务"""
        try:
            data = request.json
            schedules = load_schedules()
            
            # 查找并更新任务
            found = False
            for i, schedule_item in enumerate(schedules):
                if schedule_item.get('id') == schedule_id:
                    schedules[i].update({
                        "name": data.get('name'),
                        "device_id": data.get('device_id'),
                        "action_id": data.get('action_id'),
                        "time": data.get('time'),
                        "repeat": data.get('repeat', 'once'),
                        "weekdays": data.get('weekdays', []),
                        "enabled": data.get('enabled', True),
                        "updated_at": time_module.strftime('%Y-%m-%d %H:%M:%S', time_module.localtime())
                    })
                    found = True
                    break
            
            if not found:
                return jsonify({
                    "status": "error",
                    "message": "定时任务不存在"
                }), 404
            
            if save_schedules(schedules):
                # 重新加载调度器
                reload_scheduler()
                return jsonify({
                    "status": "success",
                    "message": "定时任务更新成功"
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "保存定时任务失败"
                }), 500
                
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"更新定时任务失败: {str(e)}"
            }), 500

    @app.route('/api/schedules/<schedule_id>', methods=['DELETE'])
    def delete_schedule(schedule_id):
        """删除定时任务"""
        try:
            schedules = load_schedules()
            schedules = [s for s in schedules if s.get('id') != schedule_id]
            
            if save_schedules(schedules):
                # 重新加载调度器
                reload_scheduler()
                return jsonify({
                    "status": "success",
                    "message": "定时任务删除成功"
                })
            else:
                return jsonify({
                    "status": "error",
                    "message": "保存定时任务失败"
                }), 500
                
        except Exception as e:
            return jsonify({
                "status": "error",
                "message": f"删除定时任务失败: {str(e)}"
            }), 500

