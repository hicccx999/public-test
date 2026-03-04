# 用 GitHub Actions 搭建临时 Shadowsocks 代理服务器

> 适用平台：Mac / Windows | 客户端：ClashX（Mac）/ Clash for Windows

---

## 整体思路

```
手动触发 GitHub Actions
        ↓
启动 Ubuntu Runner（免费）
        ↓
安装并运行 Shadowsocks
        ↓
ngrok 将端口暴露到公网
        ↓
发邮件通知你新的连接地址
        ↓
本地 ClashX 更新配置，开始使用
        ↓
6 小时后自动结束（可重新触发）
```

**免费额度：** GitHub Actions 免费账户每月 2000 分钟，每次最长运行 6 小时。

---

## 第一步：注册 ngrok 获取 Token

ngrok 用于将 GitHub Actions runner 的端口暴露到公网。

1. 打开 https://ngrok.com，注册免费账号
2. 登录后进入 Dashboard → 左侧「Your Authtoken」
3. 复制 Token，格式类似：`2abc123xyz_xxxxxxxxxxxxxx`

---

## 第二步：开启 163 邮箱 SMTP 授权码

1. 登录 https://mail.163.com
2. 顶部「设置」→「POP3/SMTP/IMAP」
3. 开启「SMTP 服务」
4. 点击「生成授权码」，记下授权码（**不是登录密码**）

---

## 第三步：创建 GitHub 仓库并配置 Secrets

### 3.1 创建仓库

1. 打开 https://github.com/new
2. 创建一个新仓库，名字随意，如 `my-proxy`
3. 可见性选 **Private（私有）**

### 3.2 添加 Secrets

进入仓库页面 → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**，依次添加以下 4 个：

| Secret 名 | 值 |
|-----------|-----|
| `SS_PASSWORD` | 自己设置的 Shadowsocks 密码，如 `MyPass123` |
| `NGROK_TOKEN` | 第一步复制的 ngrok Token |
| `MAIL_USER` | 你的 163 邮箱地址，如 `xxx@163.com` |
| `MAIL_PASSWORD` | 第二步生成的授权码 |

---

## 第四步：创建 Workflow 文件

在仓库里创建文件，路径必须是：

```
.github/workflows/proxy.yml
```

文件内容如下：

```yaml
name: SS Proxy

on:
  workflow_dispatch:

jobs:
  proxy:
    runs-on: ubuntu-latest
    steps:
      - name: Install Shadowsocks
        run: sudo apt-get install -y shadowsocks-libev

      - name: Configure Shadowsocks
        run: |
          sudo tee /etc/shadowsocks-libev/config.json > /dev/null << EOF
          {
            "server": "0.0.0.0",
            "server_port": 8388,
            "password": "${{ secrets.SS_PASSWORD }}",
            "method": "chacha20-ietf-poly1305"
          }
          EOF

      - name: Install ngrok
        run: |
          curl -sSL https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
            | sudo tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
          echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
            | sudo tee /etc/apt/sources.list.d/ngrok.list
          sudo apt update && sudo apt install -y ngrok
          ngrok config add-authtoken ${{ secrets.NGROK_TOKEN }}

      - name: Start Shadowsocks
        run: sudo systemctl start shadowsocks-libev

      - name: Start ngrok & get address
        run: |
          ngrok tcp 8388 > /dev/null &
          sleep 5
          NGROK_URL=$(curl -s http://localhost:4040/api/tunnels | python3 -c "
          import sys, json
          data = json.load(sys.stdin)
          print(data['tunnels'][0]['public_url'])
          ")
          HOST=$(echo $NGROK_URL | sed 's/tcp:\/\///' | cut -d: -f1)
          PORT=$(echo $NGROK_URL | sed 's/tcp:\/\///' | cut -d: -f2)
          echo "HOST=$HOST" >> $GITHUB_ENV
          echo "PORT=$PORT" >> $GITHUB_ENV
          echo "代理地址: $HOST:$PORT"

      - name: Send email notification
        run: |
          python3 << EOF
          import smtplib
          from email.mime.text import MIMEText

          host = "${{ env.HOST }}"
          port = "${{ env.PORT }}"
          password = "${{ secrets.SS_PASSWORD }}"

          body = f"""Shadowsocks 代理已启动，请更新 ClashX 配置：

          server:   {host}
          port:     {port}
          cipher:   chacha20-ietf-poly1305
          password: {password}

          ==============================
          ClashX / Clash for Windows config.yaml 完整配置：

          mixed-port: 7890
          allow-lan: false
          mode: rule
          log-level: info

          proxies:
            - name: "GitHub"
              type: ss
              server: {host}
              port: {port}
              cipher: chacha20-ietf-poly1305
              password: {password}

          proxy-groups:
            - name: "Proxy"
              type: select
              proxies:
                - GitHub

          rules:
            - DOMAIN-SUFFIX,github.com,Proxy
            - DOMAIN-SUFFIX,githubcopilot.com,Proxy
            - DOMAIN-SUFFIX,copilot.github.com,Proxy
            - DOMAIN-SUFFIX,api.github.com,Proxy
            - DOMAIN-SUFFIX,objects.githubusercontent.com,Proxy
            - DOMAIN-SUFFIX,vscode.dev,Proxy
            - DOMAIN-SUFFIX,marketplace.visualstudio.com,Proxy
            - DOMAIN-SUFFIX,google.com,Proxy
            - DOMAIN-SUFFIX,youtube.com,Proxy
            - DOMAIN-SUFFIX,anthropic.com,Proxy
            - MATCH,DIRECT

          ==============================
          注意：此代理最长可用 6 小时，到期后请重新触发 workflow。
          """

          msg = MIMEText(body)
          msg["Subject"] = "✅ Shadowsocks 代理已启动"
          msg["From"] = "${{ secrets.MAIL_USER }}"
          msg["To"] = "${{ secrets.MAIL_USER }}"

          with smtplib.SMTP_SSL("smtp.163.com", 465) as server:
              server.login("${{ secrets.MAIL_USER }}", "${{ secrets.MAIL_PASSWORD }}")
              server.send_message(msg)

          print("邮件发送成功")
          EOF

      - name: Keep alive (6 hours)
        run: sleep 21600
```

---

## 第五步：触发 Workflow

1. 进入 GitHub 仓库页面
2. 点击顶部「**Actions**」标签
3. 左侧找到「**SS Proxy**」
4. 点击右侧「**Run workflow**」→「**Run workflow**」确认

等待约 **1~2 分钟**，163 邮箱会收到一封包含连接信息的邮件。

---

## 第六步：更新本地 ClashX 配置

收到邮件后，把邮件里的完整 `config.yaml` 内容复制，替换本地 ClashX 的配置文件：

**Mac：** 菜单栏 ClashX 图标 → `Config` → `Open config folder` → 编辑 `config.yaml`

**Windows：** Clash for Windows → `Profiles` → 编辑当前配置文件

粘贴邮件内容后：

- **Mac**：菜单栏 ClashX → `Reload Config`
- **Windows**：Clash for Windows 自动重载

---

## 第七步：验证连接

打开浏览器访问 https://www.google.com，能打开即成功。

也可以在终端验证：

```bash
curl -x http://127.0.0.1:7890 https://www.google.com
```

---

## 6 小时后怎么办

workflow 运行 6 小时后自动结束，代理失效。重新使用时：

1. 重复「第五步」触发 workflow
2. 等待新邮件
3. 用新邮件里的配置更新 ClashX（**每次 IP 和端口都会变**）

---

## 常见问题

**Q：没收到邮件？**
检查：① 163 授权码是否正确（不是登录密码）② SMTP 服务是否已开启 ③ 查看 Actions 日志找报错

**Q：Actions 日志怎么看？**
仓库 → Actions → 点击正在运行的 workflow → 点击 `proxy` job → 展开每个步骤查看输出

**Q：邮件里的 port 每次都不一样？**
正常，ngrok 免费版每次分配随机端口，所以每次都需要更新 ClashX 配置。

**Q：GitHub Actions 免费额度够用吗？**
每月 2000 分钟，每次 6 小时 = 360 分钟，每月可以用约 **5~6 次**。

**Q：VS Code GitHub Copilot 不走代理？**
在 VS Code `settings.json` 加入：
```json
"http.proxy": "http://127.0.0.1:7890"
```
