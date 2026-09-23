#!/usr/bin/env python3
"""
Launch script for the Streamlit-based OpenChatBI interface.

Usage:
    python run_streamlit_ui.py

This will start the Streamlit server on http://localhost:8501
"""

import os
import subprocess
import sys


def main():
    """Launch the Streamlit UI"""
    # Change to the project directory
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)

    print("🚀 正在启动 SmartBI Mate Streamlit 界面...")
    print("📍 访问地址: http://localhost:8501")
    print("⏹️  按 Ctrl+C 停止服务")
    print("-" * 50)

    try:
        # Run streamlit with the new UI file
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                "sample_ui/streamlit_ui.py",
                "--server.port=8501",
                "--server.address=localhost",
            ],
            check=True,
        )
    except KeyboardInterrupt:
        print("\n👋 已停止 Streamlit 服务...")
    except subprocess.CalledProcessError as e:
        print(f"❌ 启动 Streamlit 出错: {e}")
        print("\n💡 请确认已安装 Streamlit：")
        print("   pip install streamlit")
    except FileNotFoundError:
        print("❌ 未找到 Python 或 Streamlit")
        print("\n💡 请确认已安装 Python 和 Streamlit：")
        print("   pip install streamlit")


if __name__ == "__main__":
    main()
