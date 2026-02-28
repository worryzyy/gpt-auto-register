"""
配置加载模块
从 config.yaml 文件加载配置，支持动态更新

使用方法:
    from config import cfg
    
    # 访问配置项
    total = cfg.registration.total_accounts
    email_domain = cfg.email.domain
    
    # 或者直接导入常量（兼容旧代码）
    from config import TOTAL_ACCOUNTS, EMAIL_DOMAIN
"""

import os
import sys
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, Any, List

# 尝试导入 yaml，如果未安装则提示
try:
    import yaml
except ImportError:
    print("❌ 缺少 PyYAML 依赖，请先安装:")
    print("   pip install pyyaml")
    sys.exit(1)


# ==============================================================
# 配置数据类定义
# ==============================================================

@dataclass
class RegistrationConfig:
    """注册配置"""
    total_accounts: int = 1
    min_age: int = 20
    max_age: int = 40


@dataclass
class EmailConfig:
    """邮箱服务配置"""
    worker_url: str = ""
    domain: str = ""
    prefix_length: int = 10
    wait_timeout: int = 120
    poll_interval: int = 3
    admin_password: str = ""


@dataclass
class BrowserConfig:
    """浏览器配置"""
    max_wait_time: int = 600
    short_wait_time: int = 120
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    chrome_path: str = ""  # Chrome 浏览器路径


@dataclass
class PasswordConfig:
    """密码配置"""
    length: int = 16
    charset: str = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789!@#$%"


@dataclass
class RetryConfig:
    """重试配置"""
    http_max_retries: int = 5
    http_timeout: int = 30
    error_page_max_retries: int = 5
    button_click_max_retries: int = 3


@dataclass
class BatchConfig:
    """批量注册配置"""
    interval_min: int = 5
    interval_max: int = 15


@dataclass
class FilesConfig:
    """文件路径配置"""
    accounts_file: str = "registered_accounts.txt"


@dataclass
class CreditCardConfig:
    """信用卡配置"""
    number: str = ""
    expiry: str = ""
    expiry_month: str = ""
    expiry_year: str = ""
    cvc: str = ""


@dataclass
class PaymentConfig:
    """支付配置"""
    credit_card: CreditCardConfig = field(default_factory=CreditCardConfig)


@dataclass
class Sub2ApiConfig:
    """sub2api 自动绑定配置"""
    enabled: bool = False
    base_url: str = ""
    email: str = ""
    password: str = ""
    concurrency: Optional[int] = None
    priority: Optional[int] = None
    group_ids: List[int] = field(default_factory=list)


@dataclass
class AppConfig:
    """应用程序完整配置"""
    registration: RegistrationConfig = field(default_factory=RegistrationConfig)
    email: EmailConfig = field(default_factory=EmailConfig)
    browser: BrowserConfig = field(default_factory=BrowserConfig)
    password: PasswordConfig = field(default_factory=PasswordConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    batch: BatchConfig = field(default_factory=BatchConfig)
    files: FilesConfig = field(default_factory=FilesConfig)
    payment: PaymentConfig = field(default_factory=PaymentConfig)
    sub2api: Sub2ApiConfig = field(default_factory=Sub2ApiConfig)


# ==============================================================
# 配置加载器
# ==============================================================

class ConfigLoader:
    """
    配置加载器
    支持从 YAML 文件加载配置，并合并默认值
    """
    
    # 配置文件搜索路径（按优先级排序）
    CONFIG_FILES = [
        "config.yaml",
        "config.yml",
        "config.local.yaml",
        "config.local.yml",
    ]
    
    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置加载器
        
        参数:
            config_path: 指定配置文件路径，如果为 None 则自动搜索
        """
        self.config_path = config_path
        self.raw_config: Dict[str, Any] = {}
        self.config = AppConfig()
        
        self._load_config()
    
    def _find_config_file(self) -> Optional[Path]:
        """查找配置文件"""
        # 获取脚本所在目录
        base_dir = Path(__file__).parent
        
        for filename in self.CONFIG_FILES:
            config_file = base_dir / filename
            if config_file.exists():
                return config_file
        
        return None
    
    def _load_config(self) -> None:
        """加载配置文件"""
        if self.config_path:
            config_file = Path(self.config_path)
        else:
            config_file = self._find_config_file()
        
        if config_file is None or not config_file.exists():
            print("⚠️ 未找到配置文件 config.yaml")
            print("   请复制 config.example.yaml 为 config.yaml 并修改配置")
            print("   使用默认配置继续运行...")
            return
        
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                self.raw_config = yaml.safe_load(f) or {}
            
            self.config_path = str(config_file)
            print(f"📄 已加载配置文件: {config_file.name}")
            
            # 解析配置到数据类
            self._parse_config()
            
        except yaml.YAMLError as e:
            print(f"❌ 配置文件格式错误: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ 加载配置文件失败: {e}")
            sys.exit(1)
    
    def _parse_config(self) -> None:
        """解析原始配置到数据类"""
        # 注册配置
        if 'registration' in self.raw_config:
            reg = self.raw_config['registration']
            self.config.registration = RegistrationConfig(
                total_accounts=reg.get('total_accounts', 1),
                min_age=reg.get('min_age', 20),
                max_age=reg.get('max_age', 40)
            )
        
        # 邮箱配置
        if 'email' in self.raw_config:
            email = self.raw_config['email']
            self.config.email = EmailConfig(
                worker_url=email.get('worker_url', ''),
                domain=email.get('domain', ''),
                prefix_length=email.get('prefix_length', 10),
                wait_timeout=email.get('wait_timeout', 120),
                poll_interval=email.get('poll_interval', 3),
                admin_password=email.get('admin_password', '')
            )
        
        # 浏览器配置
        if 'browser' in self.raw_config:
            browser = self.raw_config['browser']
            self.config.browser = BrowserConfig(
                max_wait_time=browser.get('max_wait_time', 600),
                short_wait_time=browser.get('short_wait_time', 120),
                user_agent=browser.get('user_agent', ''),
                chrome_path=browser.get('chrome_path', '')
            )
        
        # 密码配置
        if 'password' in self.raw_config:
            pwd = self.raw_config['password']
            self.config.password = PasswordConfig(
                length=pwd.get('length', 16),
                charset=pwd.get('charset', '')
            )
        
        # 重试配置
        if 'retry' in self.raw_config:
            retry = self.raw_config['retry']
            self.config.retry = RetryConfig(
                http_max_retries=retry.get('http_max_retries', 5),
                http_timeout=retry.get('http_timeout', 30),
                error_page_max_retries=retry.get('error_page_max_retries', 5),
                button_click_max_retries=retry.get('button_click_max_retries', 3)
            )
        
        # 批量配置
        if 'batch' in self.raw_config:
            batch = self.raw_config['batch']
            self.config.batch = BatchConfig(
                interval_min=batch.get('interval_min', 5),
                interval_max=batch.get('interval_max', 15)
            )
        
        # 文件配置
        if 'files' in self.raw_config:
            files = self.raw_config['files']
            self.config.files = FilesConfig(
                accounts_file=files.get('accounts_file', 'registered_accounts.txt')
            )
        
        # 支付配置
        if 'payment' in self.raw_config:
            payment = self.raw_config['payment']
            self.config.payment = PaymentConfig(
                credit_card=CreditCardConfig(
                    number=payment.get('credit_card', {}).get('number', ''),
                    expiry=payment.get('credit_card', {}).get('expiry', ''),
                    expiry_month=payment.get('credit_card', {}).get('expiry_month', ''),
                    expiry_year=payment.get('credit_card', {}).get('expiry_year', ''),
                    cvc=payment.get('credit_card', {}).get('cvc', '')
                )
            )

        # sub2api 自动绑定配置
        if 'sub2api' in self.raw_config:
            s2a = self.raw_config['sub2api']
            raw_group_ids = s2a.get('group_ids', [])
            if isinstance(raw_group_ids, list):
                group_ids = [int(group_id) for group_id in raw_group_ids]
            else:
                group_ids = []
            self.config.sub2api = Sub2ApiConfig(
                enabled=s2a.get('enabled', False),
                base_url=s2a.get('base_url', ''),
                email=s2a.get('email', ''),
                password=s2a.get('password', ''),
                concurrency=(int(s2a['concurrency']) if s2a.get('concurrency') is not None else None),
                priority=(int(s2a['priority']) if s2a.get('priority') is not None else None),
                group_ids=group_ids
            )
    
    def reload(self) -> None:
        """重新加载配置文件"""
        self._load_config()
    
    def get(self, key: str, default: Any = None) -> Any:
        """
        获取原始配置值（支持点号路径）
        
        参数:
            key: 配置键，支持点号分隔的路径，如 'email.domain'
            default: 默认值
        
        返回:
            配置值或默认值
        """
        keys = key.split('.')
        value = self.raw_config
        
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        
        return value


# ==============================================================
# 全局配置实例
# ==============================================================

# 创建全局配置加载器
_loader = ConfigLoader()

# 配置对象（推荐使用）
cfg = _loader.config


# ==============================================================
# 兼容性导出（保持旧代码兼容）
# ==============================================================

# 注册配置
TOTAL_ACCOUNTS = cfg.registration.total_accounts
MIN_AGE = cfg.registration.min_age
MAX_AGE = cfg.registration.max_age

# 邮箱配置
EMAIL_WORKER_URL = cfg.email.worker_url
EMAIL_DOMAIN = cfg.email.domain
EMAIL_PREFIX_LENGTH = cfg.email.prefix_length
EMAIL_WAIT_TIMEOUT = cfg.email.wait_timeout
EMAIL_POLL_INTERVAL = cfg.email.poll_interval
EMAIL_ADMIN_PASSWORD = cfg.email.admin_password

# 浏览器配置
MAX_WAIT_TIME = cfg.browser.max_wait_time
SHORT_WAIT_TIME = cfg.browser.short_wait_time
USER_AGENT = cfg.browser.user_agent
CHROME_PATH = cfg.browser.chrome_path

# 密码配置
PASSWORD_LENGTH = cfg.password.length
PASSWORD_CHARS = cfg.password.charset

# 重试配置
HTTP_MAX_RETRIES = cfg.retry.http_max_retries
HTTP_TIMEOUT = cfg.retry.http_timeout
ERROR_PAGE_MAX_RETRIES = cfg.retry.error_page_max_retries
BUTTON_CLICK_MAX_RETRIES = cfg.retry.button_click_max_retries

# 批量配置
BATCH_INTERVAL_MIN = cfg.batch.interval_min
BATCH_INTERVAL_MAX = cfg.batch.interval_max

# 文件配置
TXT_FILE = cfg.files.accounts_file

# 支付配置（字典格式，兼容旧代码）
CREDIT_CARD_INFO = {
    "number": cfg.payment.credit_card.number,
    "expiry": cfg.payment.credit_card.expiry,
    "expiry_month": cfg.payment.credit_card.expiry_month,
    "expiry_year": cfg.payment.credit_card.expiry_year,
    "cvc": cfg.payment.credit_card.cvc
}


# ==============================================================
# 工具函数
# ==============================================================

def reload_config() -> None:
    """
    重新加载配置文件
    注意：这不会更新已导入的常量，只会更新 cfg 对象
    """
    global cfg
    _loader.reload()
    cfg = _loader.config


def get_config() -> AppConfig:
    """获取当前配置对象"""
    return cfg


def print_config_summary() -> None:
    """打印配置摘要"""
    print("\n" + "=" * 50)
    print("📋 当前配置摘要")
    print("=" * 50)
    print(f"  注册账号数量: {cfg.registration.total_accounts}")
    print(f"  邮箱域名: {cfg.email.domain}")
    print(f"  Worker URL: {cfg.email.worker_url[:30]}...")
    print(f"  账号保存文件: {cfg.files.accounts_file}")
    print(f"  批量间隔: {cfg.batch.interval_min}-{cfg.batch.interval_max}秒")
    print("=" * 50 + "\n")


# 模块加载时打印一次配置信息（可选）
if __name__ == "__main__":
    print_config_summary()
