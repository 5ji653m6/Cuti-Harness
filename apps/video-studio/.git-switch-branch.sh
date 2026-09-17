#!/bin/bash
# Git 分支切换辅助脚本 - 自动处理 .env 文件

ENV_FILES=(".env.development" ".env.production")
BACKUP_DIR="/tmp"

# 备份文件
backup_env_files() {
    for file in "${ENV_FILES[@]}"; do
        if [ -f "$file" ]; then
            cp "$file" "$BACKUP_DIR/${file}.backup"
            echo "✅ 已备份: $file"
        fi
    done
}

# 恢复文件
restore_env_files() {
    for file in "${ENV_FILES[@]}"; do
        if [ -f "$BACKUP_DIR/${file}.backup" ]; then
            cp "$BACKUP_DIR/${file}.backup" "$file"
            echo "✅ 已恢复: $file"
        fi
    done
}

# 取消 skip-worktree
unskip_env_files() {
    for file in "${ENV_FILES[@]}"; do
        git update-index --no-skip-worktree "$file" 2>/dev/null
    done
}

# 设置 skip-worktree
skip_env_files() {
    for file in "${ENV_FILES[@]}"; do
        git update-index --skip-worktree "$file" 2>/dev/null
    done
    echo "✅ 已设置 skip-worktree 忽略 .env 文件"
}

# 恢复 Git 状态
restore_git_state() {
    for file in "${ENV_FILES[@]}"; do
        git restore "$file" 2>/dev/null
    done
}

# 主函数
if [ $# -eq 0 ]; then
    echo "用法: $0 <branch-name>"
    echo "示例: $0 dev"
    exit 1
fi

TARGET_BRANCH=$1
CURRENT_BRANCH=$(git branch --show-current)

echo "🔄 准备从 $CURRENT_BRANCH 切换到 $TARGET_BRANCH"

# 1. 备份当前文件
backup_env_files

# 2. 取消 skip-worktree
unskip_env_files

# 3. 恢复 Git 状态
restore_git_state

# 4. 切换分支
echo "🔄 正在切换分支..."
if git checkout "$TARGET_BRANCH"; then
    echo "✅ 成功切换到 $TARGET_BRANCH"
    
    # 5. 恢复文件
    restore_env_files
    
    # 6. 重新设置 skip-worktree
    skip_env_files
    
    echo "✅ 完成！.env 文件已恢复并设置为忽略状态"
else
    echo "❌ 切换分支失败"
    # 恢复文件
    restore_env_files
    skip_env_files
    exit 1
fi

