# DDS转换工具

一个用于批量自动将图片转换为DDS的项目，方便用于3D引擎开发中的纹理管理
可以设置路径监控3D引擎项目的资源文件夹，把拖入的图像和纹理自动转换成统一标准的dds格式

## 功能特性

- 使用nvcompress命令行工具执行文件转换
- 批量处理功能
- 实时文件夹监控
- 自动调整纹理分辨率为dds规范尺寸
- 支持多种图片格式(PNG/JPG/JPEG/BMP)
- 可调整最大分辨率(512/1024/2048)

## 安装

1. 安装Python 3.8+
2. 安装依赖：`pip install -r requirements.txt`

## 使用说明

运行`python src/main.py`直接启动
或自行打包


## 依赖

- PyQt5
- Pillow
- watchdog
