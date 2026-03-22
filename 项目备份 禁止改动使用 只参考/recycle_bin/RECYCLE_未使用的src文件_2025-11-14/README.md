# 回收站说明文件

**移动时间**: 2025-11-14

**操作原因**: 项目代码优化 - 清理未使用的src模块

**文件列表**: 
1. `chrome_installer_gui.py` - Chrome安装GUI（未在app.py中引用）
2. `confidence_scorer.py` - 置信度评分器（未在app.py中引用）
3. `config_manager.py` - 配置管理器（未在app.py中引用）
4. `post_interaction_validator.py` - 交互验证器（未在app.py中引用）
5. `quantity_extraction_enhanced.py` - 数量提取器（未在app.py中引用）
6. `trending_keywords_scraper.py` - 关键词抓取器（未在app.py中引用）

**状态**: 待用户手动测试app.py后确认是否可以永久删除

**注意**: 这些文件在app.py中未被导入或使用。等待用户启动并测试app.py后，确认项目正常运行，再进行永久删除。如需恢复，请将文件移回src/目录。

**如何恢复**: 
```powershell
# 恢复所有文件
Move-Item "recycle_bin\RECYCLE_未使用的src文件_2025-11-14\*.py" "src\" -Force

# 或恢复单个文件
Move-Item "recycle_bin\RECYCLE_未使用的src文件_2025-11-14\chrome_installer_gui.py" "src\" -Force
```





