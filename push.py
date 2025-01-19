 # git add.
# git commit -m "用命令传" ，  push.bat commit 内容
# git push origin master

import sys
import subprocess

def git_push(commit_message=None):
    try:
        # Add all changes
        subprocess.run(['git', 'add', '.'], check=True)
        
        # If no commit message provided, use a default one
        if not commit_message:
            commit_message = "更新"
        
        # Commit changes
        subprocess.run(['git', 'commit', '-m', commit_message], check=True)
        
        # Push to remote
        subprocess.run(['git', 'push', 'origin', 'master'], check=True)
        
        print("推送成功！")
    except subprocess.CalledProcessError as e:
        print(f"错误: {e}")
        
if __name__ == "__main__":
    # Get commit message from command line argument if provided
    message = sys.argv[1] if len(sys.argv) > 1 else None
    git_push(message)
