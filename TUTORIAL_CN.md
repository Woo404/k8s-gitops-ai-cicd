# k8s-gitops-ai-cicd 中文教程（自己跑通 + 面试怎么讲）

> 这是**个人学习 / 作品集项目**，不是生产系统。面试时请如实说明：
> “这是我在自己的虚拟机 / 家庭实验环境里搭的练习项目”。**不要编造用户量、可用性、节省多少时间之类的生产数据。**
> 下面每一步你都要亲手跑一遍，截你自己的图，能讲清楚每个文件为什么这么写。

## 0. 这个项目补的是什么

前两个项目已经覆盖：应用本身（FastAPI + LLM + 脱敏 + Prometheus）和云主机交付（Ansible + Terraform 部署到阿里云 ECS / AWS EC2）。
本项目补齐 JD 里剩下的几块：

| JD 关键词 | 本项目对应 |
|---|---|
| 云 & **本地（on-prem）** 基础设施 | 用 Ansible 在本地虚拟机装 k3s 集群（1 server + N agent） |
| Kubernetes / 容器编排 | Helm Chart：探针、资源限制、HPA、PDB、Ingress、可选 ServiceMonitor |
| CI/CD | GitHub Actions：ruff、pytest、helm lint/template、kubeconform、ansible-lint、shellcheck |
| GitOps / 变更管控 | Argo CD：dev 自动同步，prod 人工确认同步，靠 PR 升级镜像 tag，回滚就是 git revert |
| AI/LLM 集成、**AI 辅助开发工具** | ci-copilot：CI 失败时把日志脱敏后发给 LLM 分析根因和修复建议，LLM 不可用时退回规则引擎，结果发 PR 评论 |

## 1. 准备环境

- 一台电脑（Windows 可用 WSL2，或 Mac / Linux）
- Python 3.10+、git
- 跑集群：一台 Ubuntu 22.04/24.04 虚拟机（VirtualBox / VMware / 云主机都行），2C4G 起
- 可选：Ollama（本地大模型），`ollama pull qwen2.5:7b`，需要约 5GB 磁盘、8GB 内存比较舒服
- 安装 helm：https://helm.sh/docs/intro/install/ ；kubeconform：https://github.com/yannh/kubeconform/releases

## 2. 先跑 ci-copilot（不需要集群）

```bash
git clone https://github.com/Woo404/k8s-gitops-ai-cicd.git
cd k8s-gitops-ai-cicd
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && pytest -q            # 应看到 16 passed

# 只用规则（不连大模型）
python -m ci_copilot --log samples/failed_pytest.log --no-llm

# 连本地 Ollama
export CI_COPILOT_LLM_BASE_URL=http://localhost:11434/v1
export CI_COPILOT_LLM_MODEL=qwen2.5:7b
python -m ci_copilot --log samples/failed_helm.log --output report.md
cat report.md                         # 看 Analysis source 是不是 llm

# 审一段 diff
git diff HEAD~1 | python -m ci_copilot --diff -
```

**自己动手练习（面试最有说服力的部分）：**
1. 故意把 `tests/test_rules.py` 改错一个断言，跑 `pytest -q 2>&1 | tee my.log`，再 `python -m ci_copilot --log my.log`，看规则 / LLM 给的结论对不对。
2. 在 `samples/` 里加一个你工作中常见的错误（比如 OOM、端口占用），在 `ci_copilot/rules.py` 加一条规则，再加一个测试。
3. 把 Ollama 停掉再跑，确认它会打印 `LLM unavailable, used rule fallback`，并且 `Analysis source` 是 `rule_fallback`。

关键代码看这几个：
- `ci_copilot/redaction.py`：发给大模型之前先脱敏（GitHub token、AWS/阿里云 AK、`sk-` key、JWT、URL 里的账号密码、password=xxx、邮箱、IP、私钥）
- `ci_copilot/llm.py`：标准库实现的 OpenAI 兼容客户端；提示词要求只输出 JSON、不许编造；解析失败就抛错走兜底
- `ci_copilot/rules.py`：9 条规则（依赖缺失、测试断言、ruff、helm 渲染、K8s schema、镜像拉取、docker build、网络超时、权限）
- `ci_copilot/cli.py`：脱敏 → 截取日志尾部 → LLM → 失败则规则 → 输出 Markdown，同时写入 `$GITHUB_STEP_SUMMARY`

## 3. 本地校验 Helm Chart

```bash
./scripts/validate_k8s.sh
# 期望：helm lint 两个环境都 0 failed；kubeconform Summary: ... Invalid: 0
helm template aiops charts/aiops-log-assistant -f environments/prod/values.yaml | less
```

要能讲清楚：
- `startupProbe / livenessProbe / readinessProbe` 区别：启动慢时 startup 先兜住；liveness 失败重启容器；readiness 失败只是摘流量
- `resources.requests` 决定调度，`limits` 决定上限（内存超限会被 OOMKilled）；HPA 按 requests 的百分比算利用率，所以必须设 requests
- prod 打开 HPA（2~6 副本）、PDB（至少 1 个可用）、反亲和（尽量分散到不同节点）
- ConfigMap 变更会通过 `checksum/config` 注解触发滚动更新
- 密钥不进 values 文件，用 `existingSecret` 引用集群里手工 / 外部密钥系统创建的 Secret

## 4. 在本地虚拟机装 k3s + Argo CD

单机最简单：

```bash
sudo ./onprem/scripts/install_k3s_single_node.sh
sudo kubectl get nodes
sudo kubectl -n argocd get pods
```

多节点（用 Ansible，更贴近 JD）：

```bash
cd onprem/ansible
cp inventory.example.ini inventory.ini      # 改成你虚拟机的 IP 和用户
ansible-galaxy collection install -r requirements.yml
ansible-playbook site.yml --syntax-check
ansible-playbook site.yml
export KUBECONFIG=$PWD/kubeconfig
kubectl get nodes -o wide
```

`site.yml` 做了：关 swap、加载 br_netfilter、开 ip_forward → 装 k3s server（版本固定，已安装就跳过，保证幂等）→ 读 token 让 agent 加入 → 拉回 kubeconfig → 装固定版本的 Argo CD → 应用 AppProject 和 root app。

## 5. GitOps 流程

```bash
kubectl -n argocd port-forward svc/argocd-server 8080:443
# 浏览器打开 https://127.0.0.1:8080，用户 admin，初始密码脚本会打印出来；登录后立刻改密码
kubectl create ns aiops-prod
kubectl -n aiops-prod create secret generic aiops-llm-secret --from-literal=LLM_API_KEY=ollama
```

- `aiops-dev`：自动同步 + selfHeal。你手工 `kubectl scale` 改副本数，Argo CD 会改回去——这就是“以 Git 为准、自动纠偏”，可以现场演示。
- `aiops-prod`：不自动同步。先去 GHCR 找一个 `sha-xxxxxxx` 镜像 tag，提 PR 改 `environments/prod/values.yaml` 的 `image.tag`，CI 通过后合并，Argo CD 显示 OutOfSync，人看 diff 后点 Sync。
- 回滚：`git revert` 那个 PR，再同步。
- 如果 GHCR 包是私有的，Pod 会 `ImagePullBackOff`：要么把包设为 public，要么创建 docker-registry Secret 填到 `imagePullSecrets`。（`samples/failed_image_pull.log` 就是这个场景，ci-copilot 能识别。）

## 6. GitHub Actions

- `ci.yml`：三个 job 并行——python（ruff/pytest/CLI 冒烟）、k8s（helm lint/template + kubeconform，渲染结果作为 artifact 上传）、ansible（syntax-check + ansible-lint + shellcheck）
- `ci-copilot-example.yml`：测试输出 tee 到 `test.log`，**只有失败时**才调用本仓库的 Action（`uses: ./`）做分析，并 `gh pr comment` 发到 PR；另一个 job 对 PR diff 做建议性 review（`continue-on-error`，不阻塞合并）
- 仓库 Secret `CI_COPILOT_LLM_BASE_URL` 不配置时只走规则，日志不会离开 runner。GitHub 托管 runner 访问不到你家里的 Ollama，要么用自托管 runner，要么配一个你有权限使用的 OpenAI 兼容服务。

## 7. 面试怎么讲（STAR 提示，务必换成你自己真实做过的细节）

- **S**：做前两个项目时 CI 失败很多次（依赖没装、YAML 缩进、镜像 tag 不对），每次都要翻长日志；另外想练 K8s 和 GitOps，但没有公司集群。
- **T**：在自己的虚拟机上搭一套本地 K8s，用 GitOps 管理部署；同时做一个 AI 辅助工具，CI 失败时自动给出根因和修复建议，但不能泄露密钥、LLM 挂了也要能用。
- **A**：Ansible 写 k3s 安装角色（幂等、版本固定）；写 Helm Chart（探针、资源、HPA、PDB）；Argo CD 分 dev 自动 / prod 人工；CI 加 helm lint、kubeconform、ansible-lint；用 Python 标准库写 ci-copilot：先脱敏、只取日志尾部、要求 LLM 只返回 JSON，解析失败或超时就退回规则，并标明来源。
- **R**：只讲你能验证的结果，例如“16 个单元测试覆盖脱敏、规则、LLM 兜底；chart 两套环境 kubeconform 全部通过；我在自己的集群上演示过 selfHeal 和 git revert 回滚”。**不要说“节省了 xx% 排障时间”这种没测过的数字。**

## 8. 可能被追问

1. 为什么选 k3s 不选 kubeadm？——轻量、单二进制、自带 Traefik / local-path，适合本地和边缘；生产大集群可能用 kubeadm / 托管 ACK、EKS。能说出 k3s 默认用 SQLite / 嵌入式 etcd 的区别更好。
2. Argo CD 和在 CI 里直接 `kubectl apply` / `helm upgrade` 有什么区别？——Pull 模式，集群凭证不出集群；Git 即审计记录；漂移检测和自愈；回滚就是 revert。
3. prod 为什么不自动同步？——变更管控：银行环境要审批，人确认 diff 再同步；也可以用 sync window。
4. ci-copilot 怎么防止泄露敏感信息？LLM 胡说怎么办？——先正则脱敏（宁可多删）、默认本地模型、不配地址就只走规则；提示词要求基于输入、给置信度和证据行；只做建议，不自动改代码；输出标明是 llm 还是 rule_fallback。
5. HPA 不生效常见原因？——没装 metrics-server（k3s 默认带）、没设 requests、指标拿不到；`kubectl describe hpa` 看事件。
6. Pod 一直 ImagePullBackOff / CrashLoopBackOff 怎么排？——`kubectl describe pod` 看 Events、`kubectl logs --previous`、确认 tag 存在、拉取凭证、探针是否过严。

## 9. 上传到你自己的 GitHub 前

- 自己 clone 下来跑一遍第 2、3 步，最好也跑第 4、5 步，并截**你自己**的图（kubectl get pods、Argo CD 页面）替换 / 补充 `docs/screenshots`
- 提交记录用你自己的节奏，改动写清楚
- 不要提交 `inventory.ini`、`kubeconfig`、任何密钥（已在 `.gitignore`）
