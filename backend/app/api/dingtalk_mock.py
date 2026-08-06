"""钉钉扫码模拟页面（开发环境用）

真实钉钉扫码流程：
1. 钉钉APP扫描二维码 → 跳转钉钉授权页面 → 用户点击"允许"
2. 钉钉重定向到 redirect_uri?code=xxx&state=xxx
3. 后端通过 code 换取用户信息

Mock模式简化：
- 直接在浏览器打开 mock 页面，模拟用户"扫码+授权"
- 提交后通过 /dingtalk/scan/callback 回写状态
"""
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from loguru import logger

router = APIRouter()

# 内置的模拟用户列表，模拟钉钉通讯录
MOCK_DINGTALK_USERS = [
    {"userid": "mock_worker_001", "name": "张师傅", "mobile": "13800138001", "dept": "运维部"},
    {"userid": "mock_tech_001",   "name": "李维修", "mobile": "13800138002", "dept": "维修技术部"},
    {"userid": "mock_tech_002",   "name": "王电工", "mobile": "13800138003", "dept": "维修技术部"},
    {"userid": "mock_tech_003",   "name": "刘机械", "mobile": "13800138004", "dept": "维修技术部"},
    {"userid": "mock_admin_001",  "name": "赵主管", "mobile": "13800138005", "dept": "维修中心"},
    {"userid": "mock_user_peng",  "name": "彭师傅", "mobile": "18317661257", "dept": "维修部"},
]


@router.get("/dingtalk/mock-auth", response_class=HTMLResponse)
def mock_dingtalk_auth_page(state: str = ""):
    """模拟钉钉扫码后的授权页面"""
    users_html = ""
    for i, u in enumerate(MOCK_DINGTALK_USERS):
        users_html += f"""
        <div class="user-card" onclick="pickUser({i})">
            <div class="avatar">{u['name'][0]}</div>
            <div class="info">
                <div class="name">{u['name']}</div>
                <div class="dept">{u['dept']} · {u['mobile']}</div>
            </div>
        </div>
        """

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>钉钉扫码授权 (Mock)</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif;
    background: #f5f6f8;
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 32px 16px;
  }}
  .header {{
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 20px;
  }}
  .logo {{
    width: 36px; height: 36px;
    background: #0089FF;
    border-radius: 8px;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-weight: 700;
    font-size: 14px;
  }}
  .title {{ font-size: 18px; font-weight: 600; color: #1D2129; }}
  .subtitle {{ font-size: 13px; color: #86909C; margin-top: 4px; }}
  .card {{
    width: 100%;
    max-width: 420px;
    background: #fff;
    border-radius: 12px;
    padding: 20px;
    box-shadow: 0 2px 12px rgba(0,0,0,0.05);
  }}
  .section-title {{
    font-size: 14px;
    color: #1D2129;
    font-weight: 600;
    margin-bottom: 12px;
  }}
  .user-card {{
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px;
    border-radius: 8px;
    border: 1px solid #E5E6EB;
    cursor: pointer;
    margin-bottom: 10px;
    transition: all 0.2s;
  }}
  .user-card:hover {{
    border-color: #0089FF;
    background: #F2F7FF;
  }}
  .user-card.selected {{
    border-color: #0089FF;
    background: #E6F4FF;
  }}
  .avatar {{
    width: 40px; height: 40px;
    background: #0089FF;
    border-radius: 50%;
    display: flex;
    align-items: center;
    justify-content: center;
    color: #fff;
    font-weight: 600;
  }}
  .info .name {{ font-size: 15px; font-weight: 500; color: #1D2129; }}
  .info .dept {{ font-size: 12px; color: #86909C; margin-top: 2px; }}
  .btn {{
    width: 100%;
    padding: 12px;
    background: #0089FF;
    color: #fff;
    border: none;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 500;
    cursor: pointer;
    margin-top: 16px;
  }}
  .btn:disabled {{
    background: #C9CDD4;
    cursor: not-allowed;
  }}
  .status {{
    text-align: center;
    margin-top: 16px;
    font-size: 14px;
    color: #00B42A;
    display: none;
  }}
  .tip {{
    font-size: 12px;
    color: #86909C;
    margin-top: 16px;
    text-align: center;
  }}
</style>
</head>
<body>
  <div class="header">
    <div class="logo">D</div>
    <div>
      <div class="title">维修知识管理系统</div>
      <div class="subtitle">申请获取您的钉钉身份信息（Mock）</div>
    </div>
  </div>

  <div class="card">
    <div class="section-title">选择一个模拟用户登录</div>
    <div id="userList">
      {users_html}
    </div>
    <button id="confirmBtn" class="btn" disabled onclick="confirmAuth()">确认登录</button>
    <div id="status" class="status">授权成功！正在跳转...</div>
  </div>

  <div class="tip">开发环境模拟页面 · 真实环境会跳转到钉钉App</div>

<script>
  const state = "{state}";
  const mockUsers = {MOCK_DINGTALK_USERS};
    let selectedIndex = -1;

    function pickUser(idx) {{
      selectedIndex = idx;
      document.querySelectorAll('.user-card').forEach((el, i) => {{
        el.classList.toggle('selected', i === idx);
      }});
      document.getElementById('confirmBtn').disabled = false;
    }}

    async function confirmAuth() {{
      if (selectedIndex < 0) return;
      const u = mockUsers[selectedIndex];
      document.getElementById('confirmBtn').disabled = true;
      document.getElementById('status').style.display = 'block';

      // 回调到后端
      const resp = await fetch('/api/v1/auth/dingtalk/scan/callback', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{ state, user_info: u }})
      }});
      const data = await resp.json();
      if (data.status === 'scanned') {{
        // 关闭窗口（原页面轮询会自动检测到状态变化）
        setTimeout(() => {{
          window.close();
        }}, 500);
      }}
    }}
</script>
</body>
</html>"""
