import tkinter as tk
import json
import os
import cv2
import numpy as np
from PIL import Image, ImageTk
import threading
import config

CONFIG_FILE = "config.json"


class MinimapSelector:
    def __init__(self, root):
        self.root = root
        self.root.title("小地图校准器 - 采集卡模式")
        
        # 检查是否使用采集卡
        self.use_capture_card = config.USE_CAPTURE_CARD
        self.device_index = config.CAPTURE_DEVICE_INDEX
        
        if self.use_capture_card:
            print(f"正在初始化采集卡用于校准 (设备索引: {self.device_index})...")
            self.cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
            if not self.cap.isOpened():
                raise ValueError(f"无法打开采集卡设备 {self.device_index}")
            self.cap.set(cv2.CAP_PROP_FPS, 240)
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            print("采集卡已就绪，请在画面中框选小地图区域")
        else:
            self.cap = None
            print("警告：当前未启用采集卡模式，请使用屏幕截图模式")
        
        # --- 初始化状态 ---
        self.size = 120  # 默认小地图尺寸
        self.x = 0  # 相对于采集卡画面的左上角 X
        self.y = 0  # 相对于采集卡画面的左上角 Y
        
        # 从现有配置文件中读取上一次的位置
        self.load_initial_pos()
        
        # 创建主框架
        main_frame = tk.Frame(root)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 视频显示区域
        self.video_label = tk.Label(main_frame)
        self.video_label.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        # 控制区域
        control_frame = tk.Frame(main_frame)
        control_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=5)
        
        # 信息显示
        self.info_label = tk.Label(
            control_frame, 
            text=f"当前位置: X={self.x}, Y={self.y}, 大小={self.size}",
            font=("Microsoft YaHei", 10)
        )
        self.info_label.pack(side=tk.LEFT)
        
        # 保存按钮
        save_btn = tk.Button(
            control_frame,
            text="保存并退出 (Enter)",
            command=self.save_and_exit,
            bg="#4CAF50",
            fg="white",
            font=("Microsoft YaHei", 10, "bold"),
            padx=10,
            pady=5
        )
        save_btn.pack(side=tk.RIGHT)
        
        # 绑定键盘事件
        self.root.bind("<Return>", self.save_and_exit)
        self.root.bind("<Escape>", lambda e: self.root.destroy())
        
        # 鼠标拖拽相关变量
        self.dragging = False
        self.start_x = 0
        self.start_y = 0
        self.scale_factor = 1.0  # 显示缩放比例
        self.original_width = 640  # 采集卡原始宽度
        self.original_height = 480  # 采集卡原始高度
        
        # 绑定鼠标事件到视频标签
        self.video_label.bind("<ButtonPress-1>", self.on_press)
        self.video_label.bind("<B1-Motion>", self.on_drag)
        self.video_label.bind("<MouseWheel>", self.on_scroll)
        
        # 启动视频更新线程
        self.running = True
        self.update_video()
    
    def load_initial_pos(self):
        """尝试从 config.json 读取上次保存的坐标"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    minimap = cfg.get("MINIMAP", {})
                    if minimap:
                        self.x = minimap.get("left", 0)
                        self.y = minimap.get("top", 0)
                        self.size = minimap.get("width", 120)
            except Exception:
                pass
    
    def update_video(self):
        """持续更新视频帧"""
        if not self.running:
            return
        
        if self.use_capture_card and self.cap:
            ret, frame = self.cap.read()
            if ret:
                # 记录原始尺寸
                self.original_height, self.original_width = frame.shape[:2]
                
                # 在帧上绘制选框
                display_frame = self.draw_selection_box(frame)
                
                # 转换为 RGB 并调整大小以适应窗口
                rgb_frame = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                h, w = rgb_frame.shape[:2]
                
                # 保持宽高比缩放
                max_width = 800
                max_height = 600
                self.scale_factor = min(max_width / w, max_height / h)
                new_w = int(w * self.scale_factor)
                new_h = int(h * self.scale_factor)
                
                resized = cv2.resize(rgb_frame, (new_w, new_h))
                pil_image = Image.fromarray(resized)
                tk_image = ImageTk.PhotoImage(pil_image)
                
                # 更新显示
                self.video_label.config(image=tk_image)
                self.video_label.image = tk_image  # 保持引用防止被垃圾回收
        
        # 继续更新（约 30 FPS）
        self.root.after(33, self.update_video)
    
    def draw_selection_box(self, frame):
        """在帧上绘制选框"""
        output = frame.copy()
        
        # 绘制矩形选框（绿色边框）
        cv2.rectangle(output, (self.x, self.y), 
                     (self.x + self.size, self.y + self.size),
                     (0, 255, 0), 3)
        
        # 绘制中心十字线
        center_x = self.x + self.size // 2
        center_y = self.y + self.size // 2
        cv2.line(output, (center_x - 10, center_y), (center_x + 10, center_y), (0, 255, 0), 2)
        cv2.line(output, (center_x, center_y - 10), (center_x, center_y + 10), (0, 255, 0), 2)
        
        # 添加文字说明
        cv2.putText(output, f"Minimap: ({self.x}, {self.y}), Size: {self.size}",
                   (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
        cv2.putText(output, "Drag to move | Scroll to resize | Enter to save",
                   (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        
        return output
    
    def on_press(self, event):
        """记录鼠标按下的起始位置"""
        self.dragging = True
        self.start_x = event.x
        self.start_y = event.y
    
    def on_drag(self, event):
        """计算鼠标拖动的偏移量并移动选框"""
        if not self.dragging:
            return
        
        # 将显示坐标转换为原始采集卡坐标
        dx = (event.x - self.start_x) / self.scale_factor
        dy = (event.y - self.start_y) / self.scale_factor
        
        self.x += int(dx)
        self.y += int(dy)
        
        # 确保不超出边界
        self.x = max(0, min(self.x, self.original_width - self.size))
        self.y = max(0, min(self.y, self.original_height - self.size))
        
        self.start_x = event.x
        self.start_y = event.y
        
        # 更新信息显示
        self.info_label.config(text=f"当前位置: X={self.x}, Y={self.y}, 大小={self.size}")
    
    def on_scroll(self, event):
        """处理鼠标滚轮放大缩小"""
        if event.delta > 0:
            self.resize(5)  # 向上滚放大
        else:
            self.resize(-5)  # 向下滚缩小
    
    def resize(self, delta):
        """改变选框尺寸"""
        self.size += delta
        if self.size < 50:
            self.size = 50  # 限制最小不能低于 50 像素
        if self.size > 400:
            self.size = 400  # 限制最大不能超过 400 像素
        
        # 确保不超出边界
        self.x = max(0, min(self.x, 640 - self.size))
        self.y = max(0, min(self.y, 480 - self.size))
        
        # 更新信息显示
        self.info_label.config(text=f"当前位置: X={self.x}, Y={self.y}, 大小={self.size}")
    
    def save_and_exit(self, event=None):
        """将当前坐标写入 config.json 并退出"""
        config_data = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
            except Exception:
                pass
        
        # 更新 JSON 字典中的 MINIMAP 节点
        config_data["MINIMAP"] = {
            "top": self.y,
            "left": self.x,
            "width": self.size,
            "height": self.size
        }
        
        # 写回文件
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(config_data, f, indent=4, ensure_ascii=False)
        
        print(f"✅ 小地图区域已成功保存: top={self.y}, left={self.x}, size={self.size}")
        
        # 停止视频更新
        self.running = False
        
        # 释放采集卡
        if self.cap:
            self.cap.release()
        
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = MinimapSelector(root)
    root.mainloop()