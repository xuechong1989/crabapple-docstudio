# -*- coding: utf-8 -*-
"""
海棠文档工坊 - 服务管理器
提供图形界面来启动和停止 Web 服务
"""

import sys
import subprocess
import threading
import webbrowser
import socket
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

class ServiceManager:
    """服务管理器主窗口"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("海棠文档工坊 - 服务管理器")
        self.root.geometry("500x400")
        self.root.resizable(False, False)
        
        # 设置图标（如果有的话）
        try:
            self.root.iconbitmap(default='')
        except Exception as e:
            print(f"[服务管理器] 设置窗口图标失败: {e}")
        
        # 服务进程
        self.service_process = None
        self.is_running = False
        self.port = 8000
        
        # 项目路径（service_manager.py 在 backend/ 下，需向上一级到项目根）
        self.base_dir = Path(__file__).parent.parent
        
        # 设置样式
        self.setup_styles()
        
        # 创建界面
        self.create_widgets()
        
        # 检查服务状态
        self.check_service_status()
        
        # 定时检查状态
        self.start_status_monitor()
    
    def setup_styles(self):
        """设置界面样式"""
        style = ttk.Style()
        style.theme_use('clam')
        
        # 配置颜色
        self.colors = {
            'bg': '#1a2234',
            'fg': '#f0f4f8',
            'accent': '#00d4aa',
            'error': '#ef4444',
            'warning': '#f59e0b',
            'success': '#10b981',
            'secondary': '#94a3b8'
        }
        
        self.root.configure(bg=self.colors['bg'])
        
        # 配置按钮样式
        style.configure('Start.TButton', 
                       font=('Microsoft YaHei UI', 12, 'bold'),
                       padding=(20, 15))
        style.configure('Stop.TButton',
                       font=('Microsoft YaHei UI', 12, 'bold'),
                       padding=(20, 15))
        style.configure('Open.TButton',
                       font=('Microsoft YaHei UI', 10),
                       padding=(15, 10))
    
    def create_widgets(self):
        """创建界面组件"""
        # 主框架
        main_frame = tk.Frame(self.root, bg=self.colors['bg'])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=30, pady=20)
        
        # 标题
        title_label = tk.Label(
            main_frame,
            text="🧹 海棠文档工坊",
            font=('Microsoft YaHei UI', 20, 'bold'),
            fg=self.colors['accent'],
            bg=self.colors['bg']
        )
        title_label.pack(pady=(0, 5))
        
        subtitle_label = tk.Label(
            main_frame,
            text="服务管理器",
            font=('Microsoft YaHei UI', 12),
            fg=self.colors['secondary'],
            bg=self.colors['bg']
        )
        subtitle_label.pack(pady=(0, 30))
        
        # 状态显示框
        status_frame = tk.Frame(main_frame, bg='#243044', padx=20, pady=15)
        status_frame.pack(fill=tk.X, pady=(0, 20))
        
        status_title = tk.Label(
            status_frame,
            text="服务状态",
            font=('Microsoft YaHei UI', 10),
            fg=self.colors['secondary'],
            bg='#243044'
        )
        status_title.pack(anchor=tk.W)
        
        self.status_label = tk.Label(
            status_frame,
            text="● 检测中...",
            font=('Microsoft YaHei UI', 14, 'bold'),
            fg=self.colors['warning'],
            bg='#243044'
        )
        self.status_label.pack(anchor=tk.W, pady=(5, 0))
        
        self.url_label = tk.Label(
            status_frame,
            text="",
            font=('Microsoft YaHei UI', 10),
            fg=self.colors['accent'],
            bg='#243044',
            cursor="hand2"
        )
        self.url_label.pack(anchor=tk.W, pady=(5, 0))
        self.url_label.bind("<Button-1>", lambda e: self.open_browser())
        
        # 按钮框架
        button_frame = tk.Frame(main_frame, bg=self.colors['bg'])
        button_frame.pack(fill=tk.X, pady=20)
        
        # 启动按钮
        self.start_btn = tk.Button(
            button_frame,
            text="▶️  启动服务",
            font=('Microsoft YaHei UI', 12, 'bold'),
            fg='white',
            bg=self.colors['success'],
            activebackground='#059669',
            activeforeground='white',
            relief=tk.FLAT,
            padx=30,
            pady=12,
            cursor='hand2',
            command=self.start_service
        )
        self.start_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 10))
        
        # 停止按钮
        self.stop_btn = tk.Button(
            button_frame,
            text="⏹️  停止服务",
            font=('Microsoft YaHei UI', 12, 'bold'),
            fg='white',
            bg=self.colors['error'],
            activebackground='#dc2626',
            activeforeground='white',
            relief=tk.FLAT,
            padx=30,
            pady=12,
            cursor='hand2',
            command=self.stop_service,
            state=tk.DISABLED
        )
        self.stop_btn.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(10, 0))
        
        # 打开浏览器按钮
        self.open_btn = tk.Button(
            main_frame,
            text="🌐  打开浏览器访问",
            font=('Microsoft YaHei UI', 11),
            fg=self.colors['fg'],
            bg='#374151',
            activebackground='#4b5563',
            activeforeground='white',
            relief=tk.FLAT,
            padx=20,
            pady=10,
            cursor='hand2',
            command=self.open_browser,
            state=tk.DISABLED
        )
        self.open_btn.pack(fill=tk.X, pady=(0, 20))
        
        # 日志区域
        log_frame = tk.Frame(main_frame, bg='#111827')
        log_frame.pack(fill=tk.BOTH, expand=True)
        
        log_title = tk.Label(
            log_frame,
            text="运行日志",
            font=('Microsoft YaHei UI', 9),
            fg=self.colors['secondary'],
            bg='#111827',
            anchor=tk.W
        )
        log_title.pack(fill=tk.X, padx=10, pady=(10, 5))
        
        self.log_text = tk.Text(
            log_frame,
            height=6,
            font=('Consolas', 9),
            fg=self.colors['secondary'],
            bg='#0a0e17',
            relief=tk.FLAT,
            wrap=tk.WORD,
            state=tk.DISABLED
        )
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        
        # 版权信息
        footer = tk.Label(
            main_frame,
            text="海棠文档工坊 V3.4.00 | 端口: 8000",
            font=('Microsoft YaHei UI', 8),
            fg='#4b5563',
            bg=self.colors['bg']
        )
        footer.pack(pady=(10, 0))
    
    def log(self, message):
        """添加日志"""
        self.log_text.configure(state=tk.NORMAL)
        timestamp = time.strftime("%H:%M:%S")
        self.log_text.insert(tk.END, f"[{timestamp}] {message}\n")
        self.log_text.see(tk.END)
        self.log_text.configure(state=tk.DISABLED)
    
    def is_port_in_use(self, port):
        """检查端口是否被占用"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(('localhost', port)) == 0
    
    def check_service_status(self):
        """检查服务状态"""
        if self.is_port_in_use(self.port):
            self.update_status(True)
        else:
            self.update_status(False)
    
    def update_status(self, is_running):
        """更新状态显示"""
        self.is_running = is_running
        
        if is_running:
            self.status_label.configure(
                text="● 运行中",
                fg=self.colors['success']
            )
            self.url_label.configure(
                text=f"http://localhost:{self.port} (点击访问)"
            )
            self.start_btn.configure(state=tk.DISABLED)
            self.stop_btn.configure(state=tk.NORMAL)
            self.open_btn.configure(state=tk.NORMAL)
        else:
            self.status_label.configure(
                text="● 已停止",
                fg=self.colors['error']
            )
            self.url_label.configure(text="")
            self.start_btn.configure(state=tk.NORMAL)
            self.stop_btn.configure(state=tk.DISABLED)
            self.open_btn.configure(state=tk.DISABLED)
    
    def start_service(self):
        """启动服务"""
        if self.is_port_in_use(self.port):
            self.log(f"端口 {self.port} 已被占用，服务可能已在运行")
            self.update_status(True)
            return
        
        self.log("正在启动服务...")
        self.start_btn.configure(state=tk.DISABLED)
        
        def run_server():
            try:
                # 启动服务进程
                start_script = self.base_dir / "start_server.py"

                popen_kwargs = {
                    'cwd': str(self.base_dir),
                    'stdout': subprocess.PIPE,
                    'stderr': subprocess.STDOUT,
                }
                # Windows: 隐藏控制台窗口
                if sys.platform == 'win32':
                    startupinfo = subprocess.STARTUPINFO()
                    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startupinfo.wShowWindow = subprocess.SW_HIDE
                    popen_kwargs['startupinfo'] = startupinfo
                    popen_kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW

                self.service_process = subprocess.Popen(
                    [sys.executable, str(start_script)],
                    **popen_kwargs
                )
                
                # 等待服务启动
                for i in range(30):  # 最多等待30秒
                    time.sleep(1)
                    if self.is_port_in_use(self.port):
                        self.root.after(0, lambda: self.log("服务启动成功！"))
                        self.root.after(0, lambda: self.update_status(True))
                        return
                
                self.root.after(0, lambda: self.log("服务启动超时"))
                self.root.after(0, lambda: self.start_btn.configure(state=tk.NORMAL))
                
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda: self.log(f"启动失败: {err_msg}"))
                self.root.after(0, lambda: self.start_btn.configure(state=tk.NORMAL))
        
        threading.Thread(target=run_server, daemon=True).start()
    
    def stop_service(self):
        """停止服务"""
        self.log("正在停止服务...")
        
        try:
            # 如果有进程句柄，先尝试终止它
            if self.service_process:
                self.service_process.terminate()
                self.service_process = None
            
            # 查找并终止占用端口的进程
            if sys.platform == 'win32':
                # Windows: 使用 netstat + Python 过滤（避免 shell=True 注入风险）
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True,
                    text=True
                )

                for line in result.stdout.strip().split('\n'):
                    if f':{self.port}' in line and 'LISTENING' in line:
                        parts = line.split()
                        if len(parts) >= 5:
                            pid = parts[-1]
                            subprocess.run(
                                ['taskkill', '/F', '/PID', pid],
                                capture_output=True
                            )
                            self.log(f"已终止进程 PID: {pid}")
            
            time.sleep(1)
            self.check_service_status()
            self.log("服务已停止")
            
        except Exception as e:
            self.log(f"停止失败: {str(e)}")
    
    def open_browser(self):
        """打开浏览器"""
        if self.is_running:
            webbrowser.open(f"http://localhost:{self.port}")
            self.log("已在浏览器中打开")
    
    def start_status_monitor(self):
        """启动状态监控"""
        def monitor():
            self.check_service_status()
            self.root.after(3000, monitor)  # 每3秒检查一次
        
        self.root.after(3000, monitor)
    
    def on_closing(self):
        """窗口关闭事件"""
        if self.is_running:
            if messagebox.askyesno("确认", "服务正在运行，是否停止服务并退出？"):
                self.stop_service()
                time.sleep(1)
                self.root.destroy()
        else:
            self.root.destroy()
    
    def run(self):
        """运行主窗口"""
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.root.mainloop()


def main():
    """主入口"""
    # 设置 DPI 感知（Windows 10+）
    try:
        from ctypes import windll
        windll.shcore.SetProcessDpiAwareness(1)
    except Exception as e:
        print(f"[服务管理器] DPI感知设置失败: {e}")
    
    app = ServiceManager()
    app.run()


if __name__ == "__main__":
    main()

