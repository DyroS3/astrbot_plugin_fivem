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
    background: #0f0f1a;
    font-family: 'Noto Sans SC', 'Microsoft YaHei', 'PingFang SC', sans-serif;
    color: #e0e0e8;
    margin: 0;
    padding: 0;
  }
  .card {
    background: linear-gradient(180deg, #141425 0%, #0f0f1a 100%);
    padding: 24px;
  }
  .card-title {
    font-size: 20px;
    font-weight: 700;
    color: #00d4aa;
    margin-bottom: 18px;
  }
  .card-title .icon { font-size: 22px; }
  .divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0,212,170,0.3), transparent);
    margin: 14px 0;
  }
  .section-title {
    font-size: 13px;
    font-weight: 600;
    color: #7c7c9a;
    letter-spacing: 1px;
    margin-bottom: 10px;
  }
  .badge {
    display: inline-block;
    padding: 2px 8px;
    border-radius: 6px;
    font-size: 12px;
    font-weight: 600;
  }
  .badge-ok { background: rgba(0,212,170,0.15); color: #00d4aa; }
  .badge-warn { background: rgba(255,193,7,0.15); color: #ffc107; }
  .badge-err { background: rgba(255,82,82,0.15); color: #ff5252; }
  .row {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 8px 12px;
    border-radius: 8px;
    font-size: 14px;
  }
  .row-alt { background: rgba(255,255,255,0.03); }
  .footer {
    margin-top: 16px;
    font-size: 11px;
    color: #555570;
    text-align: right;
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
<div class="card">
  <div class="card-title"><span class="icon">🎮</span> FiveM 服务器状态</div>

  <div style="margin-bottom: 16px;">
    <div class="row">
      <span style="color:#aaa;">在线人数</span>
      <span style="font-size:18px; font-weight:700; color:#fff;">
        {{ total }}<span style="color:#666;"> / {{ max_players }}</span>
      </span>
    </div>
    <div style="margin:8px 12px 0; height:10px; background:#2a2a40; border-radius:5px; overflow:hidden;">
      <div style="width:{{ ratio }}%; height:100%; background:linear-gradient(90deg, #00d4aa, #00b894); border-radius:5px;"></div>
    </div>
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

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
    + _FOOT
)

# ── /fivem 玩家 ──

TMPL_PLAYERS = (
    _HEAD
    + """
<div class="card">
  <div class="card-title"><span class="icon">👥</span> 在线玩家 <span class="badge badge-ok" style="margin-left:8px;">{{ players|length }} 人</span></div>

  {% if players %}
  <div class="row" style="font-size:12px; color:#7c7c9a; font-weight:600;">
    <span style="width:50px;">ID</span>
    <span style="flex:1;">名称</span>
    <span style="width:100px; text-align:right;">职业</span>
  </div>
  {% for p in players %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span style="width:50px; color:#7c7c9a;">[{{ p.id }}]</span>
    <span style="flex:1;">{{ p.name }}</span>
    <span style="width:100px; text-align:right; color:#00d4aa; font-size:12px;">{{ p.job_label }}</span>
  </div>
  {% endfor %}
  {% else %}
  <div style="text-align:center; padding:24px; color:#7c7c9a;">当前没有玩家在线</div>
  {% endif %}

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
    + _FOOT
)

# ── /fivem 职业 ──

TMPL_JOB = (
    _HEAD
    + """
<div class="card">
  <div class="card-title"><span class="icon">👔</span> {{ label }} <span class="badge badge-ok" style="margin-left:8px;">{{ online }} 人在线</span></div>

  {% if players %}
  {% for p in players %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span style="width:50px; color:#7c7c9a;">[{{ p.id }}]</span>
    <span style="flex:1;">{{ p.name }}</span>
  </div>
  {% endfor %}
  {% else %}
  <div style="text-align:center; padding:24px; color:#7c7c9a;">当前无人在线</div>
  {% endif %}

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
    + _FOOT
)

# ── /fivem 自检 ──

TMPL_SELFCHECK = (
    _HEAD
    + """
<style>
  .check-icon { font-size: 16px; flex-shrink: 0; }
  .check-label { color: #aaa; flex-shrink: 0; min-width: 80px; }
  .check-value { flex: 1; text-align: right; }
  .issue-item {
    padding: 8px 12px;
    background: rgba(255,193,7,0.05);
    border-radius: 8px;
    font-size: 13px;
    color: #e0c060;
    line-height: 1.5;
  }
</style>
<div class="card">
  <div class="card-title"><span class="icon">🩺</span> FiveM 插件自检</div>

  {% for item in checks %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}" style="gap:10px;">
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
  <div class="issue-item" style="margin-bottom:4px;">• {{ issue }}</div>
  {% endfor %}
  {% else %}
  <div class="divider"></div>
  <div style="text-align:center; padding:8px; color:#00d4aa; font-size:14px;">✅ 未发现明显配置问题</div>
  {% endif %}

  <div class="footer">FiveM Server Status Plugin</div>
</div>
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
    min-width: 160px;
  }
  .cmd-desc { color: #aaa; font-size: 13px; }
</style>
<div class="card">
  <div class="card-title"><span class="icon">📖</span> FiveM 服务器状态插件</div>

  <div class="section-title">查询命令</div>
  {% for cmd in query_cmds %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span class="cmd-name">{{ cmd.usage }}</span>
    <span class="cmd-desc">{{ cmd.desc }}</span>
  </div>
  {% endfor %}

  <div style="margin-top:12px;"></div>
  <div class="section-title">管理员命令</div>
  {% for cmd in admin_cmds %}
  <div class="row {% if loop.index is odd %}row-alt{% endif %}">
    <span class="cmd-name">{{ cmd.usage }}</span>
    <span class="cmd-desc">{{ cmd.desc }}</span>
    <span style="color:#ffc107; font-size:11px; margin-left:4px;">🔒</span>
  </div>
  {% endfor %}

  <div class="divider"></div>
  <div style="font-size:12px; color:#666; line-height:1.6;">
    🔒 = 需要管理员权限<br>
    推送目标也可在 WebUI 插件配置中直接管理
  </div>

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
    + _FOOT
)
