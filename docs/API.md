# 接口

模块GET使用仓内样例，模块POST可传csv或rows与context，直接计算当前规则。/api/runs使用完整流水线并原子保存。每个阶段返回rows、quarantine、metrics；后续阶段还返回累计隔离。/api/upload接收multipart文件file。/api/runs/<id>/archive只导出一份带清单与证据的CSV，归属差异解释不完整时返回409 EVIDENCE_PAUSED。GET /api/runs/<id>返回服从归属复核结论的生效视图。GET /api/runs/<id>/attributions返回每次访问的归属复核版本与切换历史；POST /api/runs/<id>/attributions/<event_id>带version、decision（source或receiver）与可选explanation切换裁决，版本失效返回409并保留旧版与原分区证据。
