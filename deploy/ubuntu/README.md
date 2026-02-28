# Ubuntu 原生部署（systemd + Xvfb）

## 1) 前提

- Ubuntu 22.04/24.04
- 已把项目代码放到服务器目录（例如 `/home/ubuntu/gpt-auto-register`）
- 使用一个普通用户运行服务（例如 `ubuntu`）

## 2) 一键安装与启动

在项目根目录执行：

```bash
sudo bash deploy/ubuntu/setup_ubuntu_systemd.sh ubuntu /home/ubuntu/gpt-auto-register
```

可选第三个参数是服务名：

```bash
sudo bash deploy/ubuntu/setup_ubuntu_systemd.sh ubuntu /home/ubuntu/gpt-auto-register gpt-auto-register
```

## 3) 配置并发

编辑 `config.yaml`：

```yaml
batch:
  worker_count: 2
  interval_min: 3
  interval_max: 8
```

4核机器建议从 `worker_count: 2` 起步，稳定后再试 `3`。

修改后重启服务：

```bash
sudo systemctl restart gpt-auto-register.service
```

## 4) 常用运维命令

```bash
sudo systemctl status gpt-auto-register.service --no-pager
sudo journalctl -u gpt-auto-register.service -f
sudo systemctl restart gpt-auto-register.service
sudo systemctl stop gpt-auto-register.service
```

## 5) 手动前台调试

```bash
bash deploy/ubuntu/start_server.sh
```
