**电 子 科 技 大 学**

**<u>2022级</u>本科毕业设计（论文）进度计划表**

**学院名称：信息与软件工程学院 填表日期：2025年11月04日**

<table style="width:100%;">
<colgroup>
<col style="width: 10%" />
<col style="width: 8%" />
<col style="width: 10%" />
<col style="width: 13%" />
<col style="width: 10%" />
<col style="width: 14%" />
<col style="width: 17%" />
<col style="width: 13%" />
</colgroup>
<tbody>
<tr>
<td style="text-align: center;"><strong>学生姓名</strong></td>
<td colspan="2" style="text-align: center;"><strong>任彦舟</strong></td>
<td rowspan="2" style="text-align: center;"><strong>论文题目<br />
(含副标题)</strong></td>
<td colspan="4" rowspan="2"
style="text-align: center;"><strong>基于LangGraph的多智能体知识代理系统设计与实现</strong></td>
</tr>
<tr>
<td style="text-align: center;"><strong>学 号</strong></td>
<td colspan="2"
style="text-align: center;"><strong>2022090901013</strong></td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>周 次</strong></td>
<td colspan="3"
style="text-align: center;"><p><strong>主要工作计划</strong></p>
<p><strong>（内容）</strong></p></td>
<td style="text-align: center;"><strong>完成情况</strong></td>
<td style="text-align: center;"><strong>指导教师签字</strong></td>
<td style="text-align: center;"><strong>备 注</strong></td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>1-2</strong></td>
<td colspan="3"
style="text-align: center;"><strong>完成需求分析，明确知识代理核心功能，调研LangGraph框架和MCP、RAG技术方案，确定技术栈和开发环境。</strong></td>
<td style="text-align: center;"><strong>完成</strong></td>
<td style="text-align: center;"><img src="media/image1.png" /></td>
<td style="text-align: center;"></td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>3-4</strong></td>
<td colspan="3"
style="text-align: center;"><strong>设计系统整体架构，规划多智能体协作流程，定义知识库数据结构，绘制系统模块图和数据流图。</strong></td>
<td style="text-align: center;"><strong>完成</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">产物：<code>specs/001-multi-kb-agent-collab/</code>（架构/数据模型/OpenAPI）</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>5-6</strong></td>
<td colspan="3"
style="text-align: center;"><strong>搭建基础开发环境，集成LangGraph框架，实现基础Agent通信机制，完成核心Agent的骨架代码。</strong></td>
<td style="text-align: center;"><strong>部分完成</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">已完成后端/前端脚手架与基础设施接入（FastAPI/uv/Celery/Redis/Postgres/Milvus/MinIO）；LangGraph 与核心 Agent 骨架尚未落地</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>7-8</strong></td>
<td colspan="3"
style="text-align: center;"><strong>实现RAG核心模块，集成向量数据库，完成文档解析、向量化存储和检索功能，测试知识召回准确率。</strong></td>
<td style="text-align: center;"><strong>部分完成</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">已封装 Embedding/Milvus 客户端；文档解析/切分/入库与检索链路、召回评测尚未实现</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>9-10</strong></td>
<td colspan="3"
style="text-align: center;"><strong>设计MCP协作协议，实现多智能体任务分配与协调机制，完成知识管理Agent和对话Agent的基础协作逻辑。</strong></td>
<td style="text-align: center;"><strong>未开始</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">目前仅有 MCP 配置开关与契约/调研文档；协作协议、任务分配与多智能体编排未实现</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>11-12</strong></td>
<td colspan="3"
style="text-align: center;"><strong>构建个人知识库系统，实现用户对话自动记录、分类存储功能，开发知识库管理界面和查询接口。</strong></td>
<td style="text-align: center;"><strong>未开始</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">知识库/资料导入/对话记录等核心业务模型与管理页面尚未实现</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>13-14</strong></td>
<td colspan="3"
style="text-align: center;"><strong>实现持续学习机制，设计对话反馈收集模块，开发模型微调流程，实现基于历史对话的知识更新策略。</strong></td>
<td style="text-align: center;"><strong>未开始</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">反馈闭环、持续学习/微调与知识更新策略未实现</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>15-16</strong></td>
<td colspan="3"
style="text-align: center;"><strong>完成系统集成测试，优化各模块性能，修复协作流程中的问题，进行端到端功能验证和压力测试。</strong></td>
<td style="text-align: center;"><strong>未开始</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">尚未开展系统集成/端到端验证与压力测试</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"><strong>17-18</strong></td>
<td colspan="3"
style="text-align: center;"><strong>系统性能优化和部署，编写技术文档和用户手册，准备演示材料，进行最终功能验收和项目总结。</strong></td>
<td style="text-align: center;"><strong>部分完成</strong></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;">已提供 <code>quickstart.md</code> 与 <code>infra/up.ps1</code>；最终部署/性能优化/用户手册/演示材料与验收总结待完成</td>
</tr>
<tr>
<td colspan="2" style="text-align: center;"></td>
<td colspan="3" style="text-align: center;"></td>
<td style="text-align: center;"></td>
<td style="text-align: center;"><img src="media/image2.png" /></td>
<td style="text-align: center;"></td>
</tr>
</tbody>
</table>
