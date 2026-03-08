"""HTML + Jinja2 模板常量，用于 html_render 文转图"""

# ── 公共样式片段 ──

_BASE_STYLE = """
<style>
  * { margin: 0; padding: 0; box-sizing: border-box; }
  body {
    background: transparent;
    font-family: 'Microsoft YaHei', 'PingFang SC', system-ui, sans-serif;
    color: #e0e0e8;
    padding: 0;
  }
  .card {
    width: 460px;
    background: linear-gradient(135deg, #0f0f1a 0%, #1a1a2e 100%);
    border-radius: 16px;
    padding: 28px;
    border: 1px solid rgba(0, 212, 170, 0.15);
    box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
  }
  .card-title {
    font-size: 20px;
    font-weight: 700;
    color: #00d4aa;
    margin-bottom: 20px;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .card-title .icon { font-size: 22px; }
  .divider {
    height: 1px;
    background: linear-gradient(90deg, transparent, rgba(0,212,170,0.3), transparent);
    margin: 16px 0;
  }
  .section-title {
    font-size: 14px;
    font-weight: 600;
    color: #7c7c9a;
    text-transform: uppercase;
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
  .footer {
    margin-top: 18px;
    font-size: 11px;
    color: #555570;
    text-align: right;
  }
</style>
"""

# ── /fivem 状态 ──

TMPL_STATUS = (
    _BASE_STYLE
    + """
<div class="card">
  <div class="card-title">
    <span class="icon">🎮</span> FiveM 服务器状态
  </div>

  <div style="margin-bottom: 18px;">
    <div style="display:flex; justify-content:space-between; margin-bottom:6px;">
      <span style="font-size:14px; color:#aaa;">在线人数</span>
      <span style="font-size:18px; font-weight:700; color:#fff;">
        {{ total }}<span style="color:#666;"> / {{ max_players }}</span>
      </span>
    </div>
    <div style="width:100%; height:10px; background:#2a2a40; border-radius:5px; overflow:hidden;">
      <div style="width:{{ ratio }}%; height:100%; background:linear-gradient(90deg, #00d4aa, #00b894); border-radius:5px; transition:width 0.3s;"></div>
    </div>
  </div>

  {% if jobs %}
  <div class="divider"></div>
  <div class="section-title">📋 职业在线</div>
  <div style="display:flex; flex-direction:column; gap:6px;">
    {% for job in jobs %}
    <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 12px; background:rgba(255,255,255,0.03); border-radius:8px;">
      <span style="font-size:14px;">{{ job.label }}</span>
      <span class="badge badge-ok">{{ job.online }} 人</span>
    </div>
    {% endfor %}
  </div>
  {% endif %}

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
)

# ── /fivem 玩家 ──

TMPL_PLAYERS = (
    _BASE_STYLE
    + """
<div class="card">
  <div class="card-title">
    <span class="icon">👥</span> 在线玩家
    <span class="badge badge-ok" style="margin-left:auto;">{{ players|length }} 人</span>
  </div>

  {% if players %}
  <div style="display:flex; flex-direction:column; gap:4px;">
    <div style="display:flex; padding:6px 12px; font-size:12px; color:#7c7c9a; font-weight:600;">
      <span style="width:50px;">ID</span>
      <span style="flex:1;">名称</span>
      <span style="width:100px; text-align:right;">职业</span>
    </div>
    {% for p in players %}
    <div style="display:flex; align-items:center; padding:8px 12px; background:{% if loop.index is odd %}rgba(255,255,255,0.02){% else %}rgba(255,255,255,0.05){% endif %}; border-radius:6px; font-size:14px;">
      <span style="width:50px; color:#7c7c9a;">[{{ p.id }}]</span>
      <span style="flex:1; color:#e0e0e8;">{{ p.name }}</span>
      <span style="width:100px; text-align:right; color:#00d4aa; font-size:12px;">{{ p.job_label }}</span>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div style="text-align:center; padding:24px; color:#7c7c9a;">当前没有玩家在线</div>
  {% endif %}

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
)

# ── /fivem 职业 ──

TMPL_JOB = (
    _BASE_STYLE
    + """
<div class="card">
  <div class="card-title">
    <span class="icon">👔</span> {{ label }}
    <span class="badge badge-ok" style="margin-left:auto;">{{ online }} 人在线</span>
  </div>

  {% if players %}
  <div style="display:flex; flex-direction:column; gap:4px;">
    {% for p in players %}
    <div style="display:flex; align-items:center; padding:8px 12px; background:{% if loop.index is odd %}rgba(255,255,255,0.02){% else %}rgba(255,255,255,0.05){% endif %}; border-radius:6px; font-size:14px;">
      <span style="width:50px; color:#7c7c9a;">[{{ p.id }}]</span>
      <span style="flex:1; color:#e0e0e8;">{{ p.name }}</span>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div style="text-align:center; padding:24px; color:#7c7c9a;">当前无人在线</div>
  {% endif %}

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
)

# ── /fivem 自检 ──

TMPL_SELFCHECK = (
    _BASE_STYLE
    + """
<style>
  .check-item {
    display: flex; align-items: center; gap: 10px;
    padding: 8px 12px;
    background: rgba(255,255,255,0.03);
    border-radius: 8px;
    font-size: 14px;
  }
  .check-icon { font-size: 16px; flex-shrink: 0; }
  .check-label { color: #aaa; flex-shrink: 0; min-width: 90px; }
  .check-value { color: #e0e0e8; flex: 1; text-align: right; }
  .issue-item {
    display: flex; gap: 8px;
    padding: 8px 12px;
    background: rgba(255,193,7,0.05);
    border-radius: 8px;
    font-size: 13px;
    color: #e0c060;
    line-height: 1.5;
  }
</style>
<div class="card">
  <div class="card-title">
    <span class="icon">🩺</span> FiveM 插件自检
  </div>

  <div style="display:flex; flex-direction:column; gap:6px;">
    {% for item in checks %}
    <div class="check-item">
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
  </div>

  {% if issues %}
  <div class="divider"></div>
  <div class="section-title">⚠️ 建议关注</div>
  <div style="display:flex; flex-direction:column; gap:6px;">
    {% for issue in issues %}
    <div class="issue-item">
      <span style="flex-shrink:0;">•</span>
      <span>{{ issue }}</span>
    </div>
    {% endfor %}
  </div>
  {% else %}
  <div class="divider"></div>
  <div style="text-align:center; padding:8px; color:#00d4aa; font-size:14px;">✅ 未发现明显配置问题</div>
  {% endif %}

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
)

# ── /fivem 帮助 ──

TMPL_HELP = (
    _BASE_STYLE
    + """
<style>
  .cmd-row {
    display: flex; align-items: baseline; gap: 8px;
    padding: 6px 12px;
    font-size: 14px;
  }
  .cmd-name {
    color: #00d4aa;
    font-family: 'Consolas', 'Monaco', monospace;
    font-weight: 600;
    white-space: nowrap;
    min-width: 170px;
  }
  .cmd-desc { color: #aaa; font-size: 13px; }
  .cmd-lock { color: #ffc107; font-size: 11px; margin-left: 4px; }
</style>
<div class="card">
  <div class="card-title">
    <span class="icon">📖</span> FiveM 服务器状态插件
  </div>

  <div class="section-title">查询命令</div>
  <div style="display:flex; flex-direction:column; gap:2px; margin-bottom:14px;">
    {% for cmd in query_cmds %}
    <div class="cmd-row">
      <span class="cmd-name">{{ cmd.usage }}</span>
      <span class="cmd-desc">{{ cmd.desc }}</span>
    </div>
    {% endfor %}
  </div>

  <div class="section-title">管理员命令</div>
  <div style="display:flex; flex-direction:column; gap:2px;">
    {% for cmd in admin_cmds %}
    <div class="cmd-row">
      <span class="cmd-name">{{ cmd.usage }}</span>
      <span class="cmd-desc">{{ cmd.desc }}</span>
      <span class="cmd-lock">🔒</span>
    </div>
    {% endfor %}
  </div>

  <div class="divider"></div>
  <div style="font-size:12px; color:#666; line-height:1.6;">
    🔒 = 需要管理员权限<br/>
    推送目标也可在 WebUI 插件配置中直接管理
  </div>

  <div class="footer">FiveM Server Status Plugin</div>
</div>
"""
)
