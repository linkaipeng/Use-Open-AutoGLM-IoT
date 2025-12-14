# 🏠 IoT 智能家居控制中心

一个基于 [Open-AutoGLM](https://github.com/zai-org/Open-AutoGLM) 实现的 IoT AIAgent 控制系统，支持 Web 界面控制、小米音箱语音控制、AI 智能指令匹配和定时任务。

![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)
![Flask](https://img.shields.io/badge/Flask-3.0-green.svg)
![License](https://img.shields.io/badge/License-MIT-yellow.svg)


## ✨ 功能特性

- 🎛️ **Web 控制面板** - 可视化设备管理，一键触发设备操作
- 🎤 **语音控制** - 集成小米音箱，通过语音指令控制智能设备
- 🤖 **AI 智能匹配** - 使用智谱 AI 理解自然语言，智能匹配设备指令
- ⏰ **定时任务** - 支持每天/每周定时执行设备操作
- 📝 **执行日志** - 实时显示操作日志和语音指令


## 📦 安装步骤

### 1. 克隆项目

```bash
git clone https://github.com/your-username/iot.git
cd iot
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

```bash
# 复制示例配置文件
cp .env.example .env

# 编辑 .env 文件，填入你的配置
```

### 4. 配置小米音箱（可选）

如果需要使用语音控制功能：

```bash
# 复制小米配置示例
cp mi/config.py.example mi/config.py

# 编辑 mi/config.py，填入你的小米账号信息
```

### 5. 启动服务

```bash
python app.py
```

访问 http://localhost:5001 即可使用。

## ⚙️ 配置说明

### 环境变量配置 (.env)

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `FLASK_HOST` | 服务监听地址 | `0.0.0.0` |
| `FLASK_PORT` | 服务端口 | `5001` |
| `FLASK_DEBUG` | 调试模式 | `True` |
| `ZHIPU_API_KEY` | 智谱 AI API Key | 智谱开放平台的 API Key |
| `ZHIPU_API_BASE_URL` | 智谱 API 地址 | `https://open.bigmodel.cn/api/paas/v4` |
| `ZHIPU_MODEL` | 使用的模型 | `autoglm-phone` |

> 💡 获取智谱 API Key: https://open.bigmodel.cn/

### 小米音箱配置 (mi/config.py)

| 配置项 | 说明 |
|--------|------|
| `USER_ID` | 小米账号 ID（数字，非手机号） |
| `PASSWORD` | 小米账号密码 |
| `PASS_TOKEN` | 或使用 passToken 登录（需验证码时使用） |
| `DEVICE_NAME` | 音箱设备名称，如 "小爱音箱" |
| `POLL_INTERVAL` | 轮询间隔（毫秒） |

> 💡 获取 passToken 教程: https://github.com/idootop/migpt-next/issues/4

### 设备配置 (datas/devices.json)

设备配置示例：

```json
{
  "id": "living_room_ac",
  "name": "客厅空调",
  "app": "美的美居",
  "icon": "meide.webp",
  "status": "待机",
  "actions": [
    {
      "id": "turn_on",
      "name": "打开",
      "command": "打开{app}应用，打开客厅空调"
    },
    {
      "id": "turn_off",
      "name": "关闭",
      "command": "打开{app}应用，关闭客厅空调"
    }
  ]
}
```

- `{app}` 占位符会自动替换为设备的 `app` 字段值
- `icon` 对应 `icons/` 目录下的图标文件


## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件。

## 🙏 参考致谢

- [MiGPT](https://github.com/idootop/migpt-next) - 小米音箱接入参考


## ⚠️ 免责声明

> **适用范围**
> 
> 本项目为开源非营利项目，仅供学术研究或个人测试用途。严禁用于商业服务、网络攻击、数据窃取、系统破坏等违反《网络安全法》及使用者所在地司法管辖区的法律规定的场景。
>
> **非官方声明**
> 
> 本项目由第三方开发者独立开发，与小米集团及其关联方（下称"权利方"）无任何隶属/合作关系，亦未获其官方授权/认可或技术支持。项目中涉及的商标、固件、云服务的所有权利归属小米集团。若权利方主张权益，使用者应立即主动停止使用并删除本项目。
>
> **继续下载或运行本项目，即表示您已完整阅读并同意上述声明，否则请立即终止使用并彻底删除本项目。**
