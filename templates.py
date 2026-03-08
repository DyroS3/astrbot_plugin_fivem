"""HTML + Jinja2 模板常量，用于 html_render 文转图"""

# 卡片视口宽度，与 _render_image options 中的 viewport_width 保持一致
CARD_VIEWPORT_WIDTH = 520

# ── 公共 HTML 头部（含 viewport meta + 样式） ──

_HEAD = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=520">
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: #0d1117;
    font-family: 'Noto Sans SC', 'Microsoft YaHei', 'PingFang SC', sans-serif;
    color: #c9d1d9;
    line-height: 1.6;
  }
  .header {
    background: linear-gradient(135deg, #00d4aa 0%, #00b894 100%);
    padding: 24px 28px;
    color: #0d1117;
  }
  .header-title {
    font-size: 26px;
    font-weight: 800;
    letter-spacing: 0.5px;
  }
  .header-sub {
    font-size: 14px;
    opacity: 0.7;
    margin-top: 4px;
  }
  .content {
    padding: 24px 28px;
  }
  .divider {
    height: 1px;
    background: #21262d;
    margin: 18px 0;
  }
  .section-title {
    font-size: 15px;
    font-weight: 600;
    color: #8b949e;
    letter-spacing: 1.5px;
    margin-bottom: 12px;
  }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 14px 16px;
    font-size: 18px;
    border-bottom: 1px solid #161b22;
  }
  .row:last-child { border-bottom: none; }
  .row-alt { background: rgba(255,255,255,0.02); }
  .badge {
    display: inline-block;
    padding: 4px 14px;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 600;
  }
  .badge-ok { background: rgba(0,212,170,0.12); color: #00d4aa; }
  .badge-warn { background: rgba(255,193,7,0.12); color: #ffc107; }
  .badge-err { background: rgba(255,82,82,0.12); color: #ff5252; }
  .footer {
    padding: 16px 28px;
    font-size: 13px;
    color: #30363d;
    text-align: right;
    border-top: 1px solid #161b22;
  }
</style>
</head>
<body>
"""

_FOOT = """
</body>
</html>
"""

# ── /fivem 状态 ──

TMPL_STATUS = (
    _HEAD
    + """
<div class="header">
  <div class="header-title">🎮 FiveM 服务器状态</div>
  <div class="header-sub">Server Status Overview</div>
</div>
<div class="content">
  <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
    <span style="font-size:18px; color:#8b949e;">在线人数</span>
    <span style="font-size:30px; font-weight:700; color:#f0f6fc;">{{ total }} <small style="font-size:18px; color:#484f58; font-weight:400;">/ {{ max_players }}</small></span>
  </div>
  <div style="height:12px; background:#21262d; border-radius:6px; overflow:hidden; margin-bottom:20px;">
    <div style="width:{{ ratio }}%; height:100%; background:linear-gradient(90deg, #00d4aa, #00b894); border-radius:6px; min-width:8px;"></div>
  </div>

  {% if jobs %}
  <div class="divider"></div>
  <div class="section-title">📋 职业在线</div>
  {% for job in jobs %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span>{{ job.label }}</span>
    <span class="badge badge-ok">{{ job.online }} 人</span>
  </div>
  {% endfor %}
  {% endif %}
</div>
<div class="footer">FiveM Server Status Plugin</div>
"""
    + _FOOT
)

# ── /fivem 玩家 ──

TMPL_PLAYERS = (
    _HEAD
    + """
<div class="header">
  <div class="header-title">👥 在线玩家</div>
  <div class="header-sub">共 {{ players|length }} 人在线</div>
</div>
<div class="content">
  {% if players %}
  <div class="row" style="font-size:14px; color:#8b949e; font-weight:600; padding:10px 16px;">
    <span style="width:50px;">ID</span>
    <span style="flex:1;">名称</span>
    <span style="width:110px; text-align:right;">职业</span>
  </div>
  {% for p in players %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span style="width:50px; color:#8b949e;">[{{ p.id }}]</span>
    <span style="flex:1;">{{ p.name }}</span>
    <span style="width:110px; text-align:right; color:#00d4aa; font-size:14px;">{{ p.job_label }}</span>
  </div>
  {% endfor %}
  {% else %}
  <div style="text-align:center; padding:32px; color:#8b949e; font-size:18px;">当前没有玩家在线</div>
  {% endif %}
</div>
<div class="footer">FiveM Server Status Plugin</div>
"""
    + _FOOT
)

# ── /fivem 职业 ──

TMPL_JOB = (
    _HEAD
    + """
<div class="header">
  <div class="header-title">👔 {{ label }}</div>
  <div class="header-sub">共 {{ online }} 人在线</div>
</div>
<div class="content">
  {% if players %}
  {% for p in players %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span style="width:50px; color:#8b949e;">[{{ p.id }}]</span>
    <span style="flex:1;">{{ p.name }}</span>
  </div>
  {% endfor %}
  {% else %}
  <div style="text-align:center; padding:32px; color:#8b949e; font-size:18px;">当前无人在线</div>
  {% endif %}
</div>
<div class="footer">FiveM Server Status Plugin</div>
"""
    + _FOOT
)

# ── /fivem 自检 ──

TMPL_SELFCHECK = (
    _HEAD
    + """
<style>
  .check-icon { font-size: 20px; flex-shrink: 0; }
  .check-label { color: #8b949e; flex-shrink: 0; min-width: 90px; }
  .check-value { flex: 1; text-align: right; }
  .issue-item {
    padding: 12px 16px;
    background: rgba(255,193,7,0.05);
    border-radius: 8px;
    font-size: 16px;
    color: #e0c060;
    line-height: 1.6;
    margin-bottom: 6px;
  }
</style>
<div class="header">
  <div class="header-title">🩺 FiveM 插件自检</div>
  <div class="header-sub">Plugin Self Check</div>
</div>
<div class="content">
  {% for item in checks %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}" style="gap:12px;">
    <span class="check-icon">{{ item.icon }}</span>
    <span class="check-label">{{ item.label }}</span>
    <span class="check-value">
      {% if item.status == 'ok' %}<span class="badge badge-ok">{{ item.value }}</span>
      {% elif item.status == 'warn' %}<span class="badge badge-warn">{{ item.value }}</span>
      {% elif item.status == 'err' %}<span class="badge badge-err">{{ item.value }}</span>
      {% else %}{{ item.value }}{% endif %}
    </span>
  </div>
  {% endfor %}

  {% if issues %}
  <div class="divider"></div>
  <div class="section-title">⚠️ 建议关注</div>
  {% for issue in issues %}
  <div class="issue-item">• {{ issue }}</div>
  {% endfor %}
  {% else %}
  <div class="divider"></div>
  <div style="text-align:center; padding:12px; color:#00d4aa; font-size:18px;">✅ 未发现明显配置问题</div>
  {% endif %}
</div>
<div class="footer">FiveM Server Status Plugin</div>
"""
    + _FOOT
)

# ── /fivem 帮助 ──

TMPL_HELP = (
    _HEAD
    + """
<style>
  .cmd-name {
    color: #00d4aa;
    font-family: 'Consolas', 'Monaco', monospace;
    font-weight: 600;
    white-space: nowrap;
    min-width: 170px;
    font-size: 16px;
  }
  .cmd-desc { color: #8b949e; font-size: 15px; }
</style>
<div class="header">
  <div class="header-title">📖 FiveM 服务器状态插件</div>
  <div class="header-sub">Command Reference</div>
</div>
<div class="content">
  <div class="section-title">查询命令</div>
  {% for cmd in query_cmds %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span class="cmd-name">{{ cmd.usage }}</span>
    <span class="cmd-desc">{{ cmd.desc }}</span>
  </div>
  {% endfor %}

  <div class="divider"></div>
  <div class="section-title">管理员命令</div>
  {% for cmd in admin_cmds %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span class="cmd-name">{{ cmd.usage }}</span>
    <span class="cmd-desc">{{ cmd.desc }}</span>
    <span style="color:#ffc107; font-size:14px; margin-left:6px;">🔒</span>
  </div>
  {% endfor %}

  <div class="divider"></div>
  <div style="font-size:14px; color:#484f58; line-height:1.8;">
    🔒 = 需要管理员权限<br>
    推送目标也可在 WebUI 插件配置中直接管理
  </div>
</div>
<div class="footer">FiveM Server Status Plugin</div>
"""
    + _FOOT
)
