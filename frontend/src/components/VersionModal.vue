<template>
  <!-- xuechong 2026-10-09 研发BUG-0071 弹框交互统一：点击遮罩关闭 -->
  <Transition name="ds-modal">
  <div v-if="modelValue" class="modal-overlay">
    <div class="modal-content version-modal">
      <div class="modal-header">
        <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 标题emoji换单色线性SVG（版本历史正文文字一律不动） -->
        <h2><img class="dlg-logo" src="../assets/logo-white.png" alt="" />版本说明</h2>
        <button class="modal-close" @click="$emit('update:modelValue', false)" title="关闭版本说明弹窗">&times;</button>
      </div>
      <div class="modal-body">
        <div class="version-list">
          <!-- V3.4.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag current">V3.4.00</span>
              <span class="version-date">2026-10-13</span>
              <span class="version-badge">当前版本</span>
            </div>
            <ul class="version-changes">
              <li>【新增】安装授权机制：系统部署到新机器后需激活使用，首次启动打开运维管理页面（地址 /ops）查看机器码，由供应商签发授权文件后在页面上传激活；部署目录拷贝到其他电脑无法使用，到期后停用、续签上传新授权文件即恢复</li>
              <li>【新增】授权到期提醒：距到期30天内页面顶部横幅提醒，管理员可点"详情"查看机器码、授权客户、到期日，请提前联系供应商续签</li>
              <li>【安全】发行包代码保护：核心图像处理算法以编译后机器码交付，安装包内不再包含明文核心源码；程序文件带完整性校验，被篡改自动停止服务；每个客户的安装包带唯一标识，外泄可溯源</li>
            </ul>
          </div>

                    <!-- V3.3.05 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.3.05</span>
              <span class="version-date">2026-10-12</span>
            </div>
            <ul class="version-changes">
              <li>【新增】转换记录支持PDF重命名：每行新增"重命名"按钮，点击后文件名变为输入框，输入新名字回车即保存（Esc放弃、点到别处名字有改动自动保存），改名后下载的文件直接用新名字</li>
              <li>【新增】转换记录支持批量下载：表格新增勾选列（表头可全选当前页、跨页勾选不丢失），底部"批量下载"按钮一次把勾选的多条记录打成一个ZIP压缩包下载，ZIP内同名文件自动加序号</li>
              <li>【优化】批量下载ZIP包名改为纯英文数字格式（pdf-日期-时分秒），避免个别浏览器或老解压工具显示中文包名乱码</li>
              <li>【优化】转换记录弹框加宽（最大1200px、不超浏览器窗口宽度），尽量不再出现横向滚动条；上传记录弹框不变</li>
            </ul>
          </div>

                    <!-- V3.3.04 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.3.04</span>
              <span class="version-date">2026-10-12</span>
            </div>
            <ul class="version-changes">
              <li>【修复】净化误删页边正常内容：此前部分文档页面边缘的序号数字、页码、条形码、表格边框线端部、红色印章、页眉标题会被当成污渍清除，现在清除前先做内容识别，认出内容即保留</li>
              <li>【质量】污渍清除能力不变：487张样张对比验证，漏光渍、碎屑、装订孔、黑边痕的清理效果与上一版本完全一致</li>
              <li>【优化】全站大背景统一：首页的网格科技感背景扩展为所有页面共用的大背景，渐变对比加强</li>
              <li>【新增】登录页添加版权页脚（样式与内容与首页一致）</li>
            </ul>
          </div>

          <!-- V3.3.03 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.3.03</span>
              <span class="version-date">2026-10-11</span>
            </div>
            <ul class="version-changes">
              <li>【修复】图转PDF生成页码行为统一：此前单文件夹生成加页码、多文件夹批量生成不加，现在所有生成方式（手动生成、批量生成、修图后自动生成）统一由"添加页码"开关控制</li>
              <li>【新增】图转PDF左栏新增"添加页码"开关（默认开启）：勾选时生成的PDF在每页底部居中添加页码（从1开始连续编号），不勾选则全部不加</li>
            </ul>
          </div>

                    <!-- V3.3.02 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.3.02</span>
              <span class="version-date">2026-10-11</span>
            </div>
            <ul class="version-changes">
              <li>【优化】漏光净化升级：扫描仪漏光留下的污渍（页面四边蓝黑渍块、页面中部蓝灰云斑、纸面灰雾）净化后彻底清白，文字、表格、页码、印章零影响</li>
              <li>【质量】净化效果多轮复验加固：封面渍尾、标题字缝小斑点、页边缘碎屑、黑边样张右缘细长黑划痕全部清零；浅色细笔画文字（如日期数字）全程保护零误清</li>
              <li>【新增】修图期间页面锁定：一键修图/批量修图处理中，除下载、预览、记录查看、版本说明、图片切换、停止修图外，其余操作全部暂禁用，处理完成后自动恢复，防止处理中误操作互相冲突</li>
              <li>【新增】左侧文件树文件夹整行点击即可展开/收起（原来只能点行首小图标）</li>
              <li>【优化】处理进行中步骤条当前步骤圆圈外围显示旋转光环动画；处理期间操作模式下拉框同步禁用；生成进度提示统一为"文件名 (序号/总数)"格式</li>
              <li>【修复】批量修图完成后结束页不一致的问题：现在批量完成固定显示"全部完成"并自动弹出转换记录，单文件夹生成固定显示预览/下载页</li>
              <li>【优化】浏览器标签图标更换为橙红色logo（原白色图标在标签页上看不清）；图转PDF工具栏按钮样式统一</li>
              <li>【优化】清理若干重复解释性提示文字（按钮旁再用小字说明一遍按钮功能的冗余文案）</li>
            </ul>
          </div>

                    <!-- V3.3.01 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.3.01</span>
              <span class="version-date">2026-10-10</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-10-09 研发BUG-0071-图档扫描-3.3.01-整体页面优化向商用系统页面看齐 -->
              <!-- xuechong 2026-10-10 研发BUG-0071 用户复验：版本说明按两轮复验定稿状态重写
                   （原第一轮条目中"顶栏白底/按钮位置零变化"已与定稿不符） -->
              <li>【优化】整体页面观感向商用系统看齐：上传、修图、转换、下载等全部功能与操作流程保持不变</li>
              <li>【优化】全站色彩统一为一套配色规范：主色降饱和更耐看，页面底色统一浅灰，不再多种橙蓝绿混杂</li>
              <li>【优化】顶栏全站统一同款样式：首页与各功能页均为品牌橙渐变+白字，标题带系统logo与版本号</li>
              <li>【优化】全站图标统一为单色线性图标，替换原彩色emoji图标（不同电脑显示不一致的问题一并解决）；所有按钮文字左侧统一配图标</li>
              <li>【优化】全站弹窗统一同一套样式：品牌色标题栏+系统logo、标题栏可按住拖动、打开关闭渐变动画、统一圆形关闭按钮；点击弹窗外空白处不再误关弹窗</li>
              <li>【新增】删除类操作二次确认：转换记录/上传记录/操作记录的删除与双层PDF清空记录均先弹确认框（此前转换记录删除不打招呼直接删、其余弹浏览器白色系统框）</li>
              <li>【优化】不再弹出浏览器原生白色小框：创建用户成功展示初始密码、各类失败提示、有未保存修改时的离开确认，全部改为与系统风格统一的弹框与提示</li>
              <li>【优化】用户管理增强：列表增加分页（与转换记录同款），"创建用户"移至弹窗底部主操作位</li>
              <li>【优化】图片转PDF与编辑PDF左右栏布局完全一致：左栏"模式+上传"连为整体，右侧步骤条+工作区</li>
              <li>【优化】右上角用户按钮改为悬停自动展开"退出登录"菜单</li>
              <li>【新增】页面底部新增居中版权栏，公司名可点击跳转公司官网</li>
              <li>【修复】版本说明等弹窗打开时闪烁一下的问题</li>
              <li>【优化】登录页表单改为标签在输入框上方的现代排法，按钮与卡片样式精修</li>
              <li>【优化】去掉卡片悬停大弹跳、按钮上浮、荧光绿发光等过度动效，统一为轻投影与微动效</li>
            </ul>
          </div>

                    <!-- V3.3.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.3.00</span>
              <span class="version-date">2026-10-09</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-10-09 研发需求-0164-某项目-08-4.1.02-文件库管理-构建完整演示流程 -->
              <li>【新增】电子文件系统（电子档案系统）页签嵌入免登录使用：地址携带token自动登录（旧登录态自动让位）、嵌入模式管理员直通（登录态过期不再导致嵌入页接口401）、预览/下载直链自动携带凭证、嵌入页任务列表自动刷新且只显示本次进入后的记录</li>
              <!-- xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败 -->
              <li>【修复】登录过期不再等到上传时才集中报401：登录一次一年内免登录（原24小时过期），服务重启不掉线；进入系统时自动核验登录态，失效立即跳登录页提示"登录已过期，请重新登录"</li>
              <li>【优化】操作中途登录失效时立即跳转登录页并提示，不再静默清除登录态导致后续操作处处失败</li>
              <li>【优化】上传失败诊断包用户名字段纠正，排查故障时能看出是哪个用户碰到的</li>
              <!-- xuechong 2026-10-09 研发BUG-0069-图档扫描-3.3.00-修复登录过期不提示导致上传集中失败（上传入口合并为下拉选择，随版实施） -->
              <li>【优化】图片转PDF两个上传按钮合并为一个半宽"上传"按钮：鼠标悬停自动展开下拉菜单，选上传图片或上传文件夹后直接打开文件选择框，上传流程不变；左栏"图片文件管理"标题移除</li>
            </ul>
          </div>

                    <!-- V3.2.14 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.14</span>
              <span class="version-date">2026-09-18</span>
            </div>
            <ul class="version-changes">
              <li>【修复】修图不再误清贴边孤立文字行：页码"- N -"、页脚网址行等贴边成行小字不再被当作扫描灰尘误删，散点清理、推土机、噪点清理三环节统一按字形高度甄别豁免，灰尘清理能力不变</li>
              <li>【修复】页码全模式保留：单据模式票外页码不再被整体清除或残留半截（紧贴票边的页码同样完整保留），普通文档模式页码同样纳入保护</li>
              <li>【修复】编辑PDF页面图片DPI元数据修正：修图按页面真实渲染DPI处理（存量页面自动兼容），页码等小字不再因DPI误读被误清</li>
              <li>【质量】全量453样张两层测试：差异全部为贴边内容保留方向（无误删方向），质量扫描无新增告警</li>
            </ul>
          </div>

                    <!-- V3.2.13 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.13</span>
              <span class="version-date">2026-09-17</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-17 研发BUG-0057-图档扫描-3.2.13-修复编辑PDF模块页面加载问题 更新说明 -->
              <li>【优化】编辑PDF页面加载全面提速：切换文件即时显示页面列表，缩略图边看边出，大文件不再长时间显示"正在加载PDF页面"</li>
              <li>【优化】看过的文件切换回时图片全部走浏览器缓存，不再重复下载；翻页后台预取下一页，连续翻页无等待</li>
              <li>【修复】上传后首文件加载期间界面无任何指示（显示空白）的问题</li>
              <li>【修复】保存/还原页面时整个系统短暂无响应（下载、预览同时被卡住）的问题</li>
              <li>【修复】对未完整加载的文件执行一键处理/OCR全部时可能漏页的问题</li>
              <li>【优化】一键处理勾选添加页码时，完成提示引导到操作记录预览/下载查看页码效果；新上传文件自动清除上一轮完成提示</li>
            </ul>
          </div>

                    <!-- V3.2.12 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.12</span>
              <span class="version-date">2026-09-14</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-14 研发BUG-0053-图档扫描-3.2.11-修复编辑PDF模块带页码单据修图异常 更新说明 -->
              <li>【修复】编辑PDF模块对已带页码的单据类PDF执行修图（一键处理勾选修图、单页修图）时处理失败的问题；单据边界外的页码等暗色内容不再触发修图异常</li>
              <li>【优化】随修复一并恢复单据边缘外的小面积彩色噪点、纸缘晕影清理（该清理自3.1.08起未生效）；单据内部内容不受影响</li>
            </ul>
          </div>

                    <!-- V3.2.11 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.11</span>
              <span class="version-date">2026-09-14</span>
            </div>
            <ul class="version-changes">
              <li>【修复】编辑PDF对已有页码的PDF再次添加页码时，部分旧页码残留的问题（页脚区域有表格表头、地址等正文文字与旧页码共存时，此前无法识别旧页码，导致新旧两套页码同页出现）</li>
              <li>【优化】旧页码识别更智能：按"- 数字 -"页码外形逐组识别，并结合跨页规律校验（页码连续编号、每页位置固定、字体统一），正文再怎么排版都不会被误当成页码删除</li>
              <li>【质量】零误删保障：识别把握不准时一律不动原文，行为与旧版本完全一致；空白页判定与下载功能均无任何变化</li>
            </ul>
          </div>

                    <!-- V3.2.10 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.10</span>
              <span class="version-date">2026-09-12</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-12 研发需求-0167-图档扫描-3.2.10-编辑PDF模块处理流程与交互体验优化 更新说明 -->
              <li>【新增】「一键处理」：原「一键修图」升级，点击弹出选项面板，可组合选择修图（AI清洁+OCR）、去除空白页、添加页码、PDF瘦身；已处理过的选项自动置灰标注，避免重复操作</li>
              <li>【新增】处理效果长期生效：去除空白页、添加页码、PDF瘦身设置后持续有效，之后编辑页面再下载会自动带上这些效果与最新修改，无需重新处理；编辑过的页面只做增量更新，下载速度更快</li>
              <li>【新增】操作记录新增"操作内容"列，清晰记录每个PDF执行过的操作；操作记录的预览/下载始终展示该文件的最新处理结果；处理完成的成果独立保存，不受任务清理影响</li>
              <li>【新增】空白页可视化提示：去除空白页后，页面列表与预览区对空白页显示"导出时去除"角标与水印，一眼区分；正常编辑不受影响</li>
              <li>【修复】一键复原现在会真正还原文件：编辑保存后点一键复原，下载与操作记录中的PDF同步复原（此前仅画面还原，文件未变）；修图过的页面还原后回到修图状态</li>
              <li>【修复】页面编辑保存后切换页面再切回，保存按钮不再误亮起；切换其他文件再切回，已保存的涂抹内容不再"消失"显示</li>
              <li>【修复】添加页码时自动识别并移除旧页码后重新编号，避免出现双重页码</li>
              <li>【优化】下载更快捷：处理完成后的文件直接秒下载，编辑过的文件仅增量更新；下载操作不再写操作记录（处理情况以操作记录为准）；下载次数统计覆盖主界面与批量下载</li>
              <li>【优化】批量处理更智能：勾选即处理对象（与当前查看的文件无关，未勾选时提示先选择）；混合状态批量处理时自动跳过已处理过的文件并在完成提示中汇总</li>
              <li>【优化】界面精简：页面顶部原有三个处理开关移入「一键处理」选项面板</li>
            </ul>
          </div>
          <!-- V3.2.09 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.09</span>
              <span class="version-date">2026-09-10</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-10 研发需求-0166-图档扫描-3.2.09-增加批量编辑PDF功能 更新说明 -->
              <li>【新增】编辑PDF支持批量操作：PDF文件列表每项增加勾选框，可多选后批量一键修图、批量下载（默认仅勾选第一个文件，不勾选时行为与原单文件模式完全一致）</li>
              <li>【新增】批量一键修图：勾选2个及以上文件后「一键修图」按钮变为批量模式（显示N个），对勾选文件逐个顺序执行AI清洁+OCR；单个文件失败不影响其余文件，结束汇总成功/失败明细（含失败原因）</li>
              <li>【新增】批量下载：勾选2个及以上文件后「下载PDF」按钮变为批量模式（显示N个），一次下载ZIP压缩包；「去除空白页」「添加页码」「PDF瘦身」开关对全部勾选文件统一生效，处理结果与逐个下载完全一致；ZIP内保留原文件夹层级结构</li>
              <li>【优化】批量修图对从未打开查看过的文件自动先提取页面再处理（此前需先点开文件）；页面提取与查看并发时自动加锁防止重复提取</li>
              <li>【修复】一次上传多个PDF时第2个及以后文件的操作记录丢失问题（批量场景下影响放大）；任务/文件标识增加合法性校验与路径越界防护</li>
            </ul>
          </div>
          <!-- V3.2.08 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.08</span>
              <span class="version-date">2026-09-09</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-09 研发需求-0162-图档扫描-3.2.08-新增校验与删除空白页功能 更新说明 -->
              <li>【新增】图片转PDF自动忽略空白页：无文字/签章/表格的空白页（含仅有灰尘、装订孔、背面透印浅影的页）不再进入生成的PDF，完成时提示忽略数量；页码仅对保留内容页从1连续编号</li>
              <li>【新增】编辑PDF新增「去除空白页」开关：勾选后下载时自动检测并删除空白页，可与「添加页码」「PDF瘦身」同时勾选</li>
              <li>【优化】带页码的PDF删除空白页后自动重新连续编号：自动移除旧页码再按新页序重编，不出现断号或重复页码</li>
              <li>【说明】含少量真实文字的页面不会被误判为空白（宁可不删、绝不误删）；无彩色且极浅的淡字签名与透印痕迹物理上无法区分，此类页面请勿开启去除空白页</li>
            </ul>
          </div>
          <!-- V3.2.07 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.07</span>
              <span class="version-date">2026-09-05</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-05 研发需求-0161-图档扫描-3.2.07-上传失败弹窗增加诊断日志抓取 更新说明 -->
              <li>【新增】上传文件夹失败时自动抓取诊断信息写入运行日志：每个失败文件的HTTP状态码与后端原因、前端版本、页面运行时长一并记录，排查失败原因不再依赖浏览器开发者工具</li>
              <li>【优化】上传失败提示直接显示状态码（如"文件名(HTTP 401)"）：一眼区分登录过期、服务错误、网络问题</li>
              <li>【优化】登录鉴权拒绝写入运行日志：未登录、登录过期、登录已撤销等情况逐条记录接口与原因（此前日志中无任何痕迹），其中"签名无效"可直接判定为服务重启后需要重新登录</li>
              <li>【优化】前后端版本不一致提示升级：自动判断该"刷新页面"还是"重启服务"并给出对应指引（此前刷新解决不了时也只会提示刷新）；提示可关闭，每次打开页面只提醒一次，打开页面立即检测</li>
              <li>【修复】静态资源缓存配置恢复标准值（历史版本号替换误伤导致缓存策略失效）</li>
            </ul>
          </div>

          <!-- V3.2.06 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.06</span>
              <span class="version-date">2026-09-04</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-04 研发需求-0160-图档扫描-3.2.06-新增前端警告信息一键复制功能 更新说明 -->
              <li>【新增】错误警告条一键复制：点击警告条文字即可复制完整内容（含上传失败的文件清单），直接粘贴即可反馈给他人；复制成功后警告条下方显示绿色"✓ 已复制到剪贴板"提示</li>
              <li>【新增】警告条文字仍可手动选中复制：拖选部分文字松开不会触发全文复制，可自由复制选中片段（Ctrl+C）</li>
              <li>【优化】错误警告条关闭方式调整：由"点击警告条任意位置即关闭"改为右侧 × 按钮关闭，避免误触丢失错误信息；错误提示依然持久显示不自动消失</li>
              <li>【新增】编辑PDF添加文件夹/多选文件混入非PDF文件时，红色警告条明示"已忽略 N 个非PDF文件"及扩展名明细（此前被静默忽略无任何提示），样式与图片转PDF模块一致</li>
              <li>【修复】首页/编辑PDF/双层PDF页提示统一：此前部分页面的错误提示3秒自动消失（一闪而过看不清也复制不了），现全站统一为持久显示、可复制、可关闭</li>
            </ul>
          </div>

          <!-- V3.2.05 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.05</span>
              <span class="version-date">2026-09-04</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-04 研发BUG-0043-图档扫描-3.2.05-修复图片转PDF之后体积异常增大的问题 更新说明 -->
              <li>【修复】图片转PDF输出PDF体积异常增大（原约3倍）：根治每页重复内嵌全量中文字库问题，新生成PDF字库由约3.5MB/页降至整本约20KB，图片清晰度、页面尺寸、OCR文字搜索均不受影响</li>
              <li>【新增】编辑PDF页头新增「PDF瘦身」开关：对3.2.05之前生成的历史大PDF，勾选后点击「下载PDF」即可一键瘦身，可与「添加页码」同时勾选</li>
              <li>【优化】「添加页码」与「PDF瘦身」严格分离：只勾选添加页码时文件体积保持不变（增量追加），只有勾选PDF瘦身才做字体瘦身</li>
              <li>【新增】运维存量瘦身脚本：支持对服务器历史PDF批量扫描/一键瘦身，处理前自动备份并逐份校验</li>
              <li>【质量】全量样张两层测试 453/453 逐像素一致（零回归），55页大文档生成回归通过</li>
            </ul>
          </div>

          <!-- V3.2.04 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.04</span>
              <span class="version-date">2026-09-02</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-02 研发BUG-0041-图档扫描-3.2.04-修复PDF页码遮挡正文内容的问题 更新说明 -->
              <li>【修复】PDF页码遮挡正文问题：票据占满整页或延伸到页面底部时，添加页码不再覆盖票据——系统自动检测页码区域，已有内容时优先将页面整体上移（顶部有空间时尺寸不变），否则等比缩小并预留底部页码区域</li>
              <li>【说明】页码规格不变（宋体、黑色、10号字、- X - 样式、底部居中），每页页码保留、编号连续；内容变换采用PDF标准矩阵，双层PDF文字搜索不受影响</li>
            </ul>
          </div>

          <!-- V3.2.03 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.03</span>
              <span class="version-date">2026-09-02</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-02 研发BUG-0040-图档扫描-3.2.03-编辑PDF模块若干问题修复 更新说明 -->
              <li>【修复】编辑PDF模块单个PDF文件大小上限由 200MB 放宽到 1GB，大体积PDF可正常上传；超限提示文案同步更新为 1GB</li>
              <li>【优化】上传前即时校验文件大小：选定文件后立即检测，超过 1GB 的PDF直接提示并终止上传，不再等待整个文件传输完成后才报错</li>
              <li>【说明】文件夹上传时非PDF文件始终静默忽略不报错；点击选择文件夹后浏览器弹出的「是否将 n 个文件上传到此站点」计数为浏览器自身行为（统计全部文件），网页无法定制</li>
            </ul>
          </div>

          <!-- V3.2.02 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.02</span>
              <span class="version-date">2026-09-01</span>
            </div>
            <ul class="version-changes">
              <!-- zhaoqiaotong 2026-09-01 研发需求-0141-图档扫描-3.2.02-新增编辑PDF模块添加页码功能 更新说明 -->
              <li>【新增】编辑PDF模块支持添加页码：页头新增「添加页码」开关，开启后下载的PDF每页底部居中叠加页码（- 1 - 格式，宋体、黑色、10号字），与图片转PDF生成的页码完全一致；适用于 3.2.00 之前生成的未带页码旧PDF重新上传后补加页码</li>
              <li>【稳定】开关默认关闭，不影响既有下载行为；页码字体缺失等异常时自动回退为不带页码的正常下载，任何既有功能不受影响</li>
            </ul>
          </div>

          <!-- V3.2.01 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.01</span>
              <span class="version-date">2026-09-01</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-09-01 研发需求-0139-图档扫描-3.2.01-图片转PDF净化功能结合GLM视觉模型算法优化 更新说明 -->
              <li>【优化】页面方向矫正门控：表格小字方向判别接近随机时不再误翻整页（翻转强证据阈值提升至 0.7）</li>
              <li>【优化】深核邻域保护：OCR 检测不到的小号浅色文字不再被误淡化导致识别失败</li>
              <li>【新增】整页灰雾门控：自动识别并清理扫描件整页灰雾底，工程图纸剖面线、表格印刷底纹等局部灰内容不受影响；实测灰雾覆盖 21.0%→5.1%、13.4%→5.0%</li>
              <li>【说明】微小深色孤立斑清除、票据边缘浅色划痕修补经实验证实超出传统算法能力边界，本次默认关闭、代码保留备查</li>
            </ul>
          </div>

                    <!-- V3.2.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.2.00</span>
              <span class="version-date">2026-08-28</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 更新说明 -->
              <li>【新增】图片转PDF默认添加页码：每页底部居中，从 1 开始连续编号，宋体、黑色、10号字（距下边缘约7毫米，白底衬保证可读）</li>
              <li>【优化】页码字体升级为内嵌开源宋体（Noto Serif SC 子集，随程序包离线分发，不依赖服务器系统字体），替代原 Times-Roman 模拟宋体</li>
              <li>【稳定】页码功能整体兜底：字体文件缺失或绘制异常时自动放弃页码并记录日志，PDF 生成流程不受任何影响（生成结果与不带页码时完全一致）</li>
              <li>【质量】零回归验证：新旧版本产物逐页对比，除页码条区域外像素零差异；OCR 可搜索文字层不受影响</li>
              <!-- xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 适应性/可移植性/提示明确性整改 更新说明 -->
              <li>【稳定】历史记录与任务数据文件损坏时自动备份原文件（.corrupt-时间戳）并醒目记录日志，不再静默丢失；url.conf 配置缺失时启动即醒目提示实际生效的数据目录与恢复方式</li>
              <li>【修复】登录环节不再误报：服务未启动/服务异常时明确提示"无法连接服务/服务异常"，不再显示"用户名或密码错误"；会话签发失败也不再返回假登录成功</li>
              <li>【体验】错误提示全面升级：错误类提示不再3秒消失（点击关闭）；上传/保存/转换失败统一翻译成含原因与恢复方式的中文提示；上传部分文件失败时明确列出失败文件清单；开启了页码但未添加成功时任务消息明确告知</li>
              <li>【体验】双层PDF转换进度获取连续失败时停止刷新并明确提示，不再永久停滞无感知</li>
              <!-- xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 Windows开发环境迁移前端产物缺失白屏修复 更新说明 -->
              <li>【修复】Windows开发环境迁移后页面白屏问题：前端构建产物（frontend\dist）纳入版本管理随项目迁移；启动脚本检测产物缺失时醒目报错并给出恢复方式（不再静默启动白屏服务）；中文启动脚本编码根治（GBK+chcp 936），消除启动日志乱码与行错位</li>
              <!-- xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 前端非图片文件过滤（方案A）更新说明 -->
              <li>【优化】图片转PDF上传文件夹时自动过滤非图片文件：归档文件夹中混入的 PDF/Word 等非图片文件不再进入上传队列（此前读不动的非图片文件会触发"整体中止"导致全部图片上传失败），忽略数量持久提示；所选文件夹无图片时明确提示；白名单与后端严格一致（PNG/JPG/JPEG/BMP/TIF/TIFF/WEBP，大小写不敏感）</li>
              <!-- xuechong 2026-08-28 研发需求-0138-图档扫描-3.2.00-PDF添加页码 批量修图完成态修复 更新说明 -->
              <li>【优化】批量一键修图完成后不再出现任何中间页面或多余点击：PDF 全部自动生成完毕的瞬间直接弹出"转换记录"，立即可预览/下载（此前界面停留在"生成PDF"按钮前造成需要手动点击的误解）；步骤条同步全部标记完成</li>
            </ul>
          </div>

                    <!-- V3.1.10 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.10</span>
              <span class="version-date">2026-08-27</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-08-27 研发需求-0137-图档扫描-3.1.10-目录结构调整以方便备份和管理 更新说明 -->
              <li>【重构】项目目录结构整体重组：后端代码包 document_scanner 改名 backend（与 frontend 命名对称），启动、打包、测试、文档全部引用同步更新</li>
              <li>【重构】大体积资产统一收纳至 assets 目录（linux\wheels 生产离线依赖、windows 内网迁移安装器与依赖、models YOLO 模型），备份与管理时排除单一目录即可</li>
              <li>【优化】文档目录扁平化：docs 下不再分级，文件名以"环境-机器"前缀区分（生产-某项目-*、开发-Windows-*），Windows 迁移文档同步集中</li>
              <li>【新增】项目根 README：完整目录结构说明与备份口径（必须备份/单独备份/可自动重建三类清单）</li>
              <li>【质量】功能行为零变化：456 张全量样张新旧目录结构 A/B 逐像素对比完全一致（零回归），绝对质量扫描与上一版本持平</li>
            </ul>
          </div>

                    <!-- V3.1.09 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.09</span>
              <span class="version-date">2026-08-27</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-08-24 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化 更新说明 -->
              <li>【BUG修复】数据目录改名/整体迁移后，用户任务与历史记录里存的旧目录绝对路径失效导致文件树加载失败：服务启动时自动把旧路径重映射到新目录，仅当目标文件真实存在才替换（回写前自动备份），正常环境零改动</li>
              <li>【优化】文件树接口健壮性：任务目录被移动/删除时返回空列表，前端不再弹"文件树加载失败"错误</li>
              <li>【BUG修复】竖版扫描、票据横放（需90°旋转）的样张净化矫正后仍歪斜：此类场景倾斜检测发生在旋转之前，票据文字行呈垂直方向形成检测盲区，首轮按纸张边框角过矫且无二次矫正（典型样张残留 3.6°）。新增旋转后二次倾斜矫正，且二次检测结果必须与投影法一致（差异超 0.5° 判定假信号拒绝）才执行；456 张全量两层实测 13 张改善归零、0 张劣化</li>
              <li>【工具】新增迁移环境自检脚本 scripts/verify_env.py：内网机迁移后一键体检（Python/依赖/数据目录/陈旧路径/模型/前端产物六项）</li>
              <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化 更新说明（工具栏交互反馈修复） -->
              <li>【BUG修复】图片转PDF模块恢复任务后点击"一键修图"等工具栏按钮无反应无提示（根因修复）：①步骤1视图的事件接线缺失导致一键修图/批量修图/批量重绘的点击事件凭空消失，已补全（手动上传后操作正常、恢复任务首开不正常的差异即源于此）；②悬停展开交互保持原样，选择菜单项后菜单自动收起；③批量修图前置条件不满足时必有提示，禁用按钮悬停显示不可用原因；④移除全链路未实现的"一键修图设置"死菜单项</li>
              <li>【优化】本机调试体验：localhost 访问登录页免验证码并预填管理员账号（非本地访问行为不变）</li>
              <!-- xuechong 2026-08-26 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化 更新说明（未完成任务与断点续跑） -->
              <li>【优化】任务恢复机制重构：进入图片转PDF不再自动恢复上次任务（页面保持干净初始态），新增右上角"未完成任务"按钮与弹框集中管理未转换任务（等待处理/处理中/已中断），由用户主动选择恢复；首页"进行中的任务"横幅同步移除</li>
              <li>【优化】一键修图可靠性：修图进度与已完成清单每张实时落盘，服务重启后可从断点续跑（已修好的图片不再重复处理，实测验证）；修图中断的任务在弹框中可见可恢复；前端轮询检测到服务重启自动停止并引导恢复，不再永久转圈</li>
              <li>【BUG修复】从"未完成任务"恢复的任务在导入页直接批量修图后，完成后未自动跳转生成PDF：手动模式下面板切换被导入视图遮挡，已修复为先进入修图净化步骤再切换（该路径因步骤1按钮事件修复而首次可用）</li>
              <li>【优化】用户管理列表排序：按创建时间倒序为主、最后登录倒序为辅显示，最新创建的用户始终在最上方</li>
              <!-- xuechong 2026-08-27 研发BUG-0032-图档扫描-3.1.09-开发环境迁移机制与功能优化 更新说明（部署启动与上传机制） -->
              <li>【优化】一键部署智能化：start.bat 启动时自动体检虚拟环境——健康直接使用、损坏自动删除重建、缺失自动创建，无需人工干预 .venv 目录</li>
              <li>【优化】依赖安装本地优先：检测到项目自带离线依赖包时优先本地安装（快且版本经全量测试锁定），本地缺失或安装失败才联网下载</li>
              <li>【BUG修复】中文 Windows（GBK 区域）机器上首次安装依赖报 UnicodeDecodeError：依赖清单补 UTF-8 编码声明并在安装时强制 UTF-8 模式，跨机器部署不再依赖系统区域设置</li>
              <li>【优化】取消单次上传的批次总大小限制：实测上传接收逐文件落盘、内存峰值仅相当于单个文件（≤200MB 上限保留），总量限制并无内存依据；大批次上传不再被 413 拒绝</li>
              <li>【BUG修复】上传失败只报"网络错误"、定位不到问题文件：新增上传前逐文件可读性预检（流式读完整文件，中段损坏/已被移动/被占用/占位盘全部提前暴露）；并按整体成败语义执行——任何一个文件无法读取，整个上传立即中止并点名文件完整路径，绝不部分上传（档案列表缺一页不可接受）</li>
              <li>【优化】大批次上传可靠性：改为每批100个文件分批上传，某批失败自动二分递归定位到具体失败文件；定位出任何失败文件即整体判失败并自动删除服务端不完整任务，用户永远不会拿到缺文件的列表继续后续操作</li>
              <li>【优化】上传故障排查前后端双侧留痕：失败文件完整路径同时写入浏览器Console（F12永久可见）、上传弹窗与服务端日志（前端预检跳过清单随请求上报后端落盘）；浏览器错误翻译为明确原因（文件已被移走/服务未启动/上传超时），弹窗持久显示不再只闪3秒</li>
              <li>【BUG修复】后端已上传成功但加载文件列表环节出错时被误报为"上传失败"：上传成功后的后续处理单独捕获，真实区分"上传失败"与"上传后加载失败"，不再误导排查方向</li>
            </ul>
          </div>

                    <!-- V3.1.08 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.08</span>
              <span class="version-date">2026-08-21</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-08-21 研发BUG-0030-图档扫描-3.1.08-系统整体功能与性能优化 更新说明 -->
              <li>【BUG修复】票据纸张外的大块黑色扫描污染（黑渍/黑线/晕影）被误保留：新增三层甄别+印章形状识别（圆/椭圆/方形及残缺形态保护，仅清除边界不规则的污染块），紧贴票据的骑缝章/溢出文字照常保护，历史案例逐张验证零误伤</li>
              <li>【优化】净化防误删三重保险：钉痕带外严格模式、小噪点例外、覆盖率保护，均带开关可一键回退</li>
              <li>【优化】净化速度提升约一倍：三处检测算法向量化，456张样张实测平均 11.4→5.9 秒、最慢 36.9→14.1 秒，输出逐像素零变化</li>
              <li>【测试】历史"印章/条形码消失"问题验证已修复（22张全检）；全库无误删实例；新增文字保留率+残斑双向度量工具</li>
            </ul>
          </div>

                    <!-- V3.1.07 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.07</span>
              <span class="version-date">2026-08-20</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-08-20 研发BUG-0028-图档扫描-3.1.07-票据单据倾斜矫正角度矫正问题 更新说明 -->
              <li>【BUG修复】票据/单据倾斜矫正角度欠检：手写票据类样张（发运签收单等）文字行通道只能形成 2~9 个样本（不可靠）却拿最高权重，倾斜只被纠出一部分，输出仍肉眼可见歪斜（典型样张 121.tif 原图歪 1.47° 只纠 0.81°，输出剩余 0.52°）。新增投影法仲裁门控：文字行小样本且投影法高置信、与现有决策分歧大时，采纳投影角为最终矫正角。全库 456 张样张两层实测：欠检样张矫正后剩余倾斜全部归零，其余 420 张输出逐像素不变（零回归），逐张劣化 0 张；可用 DESKEW_PROJ_ARBITRATION 开关一键回滚旧行为</li>
              <li>【测试】全量两层测试通过：A/B 回归 420 张逐像素一致 + 36 张差异精确等于预期修复清单；绝对质量扫描倾斜告警 28→10 张（剩余 10 张为既有问题原样保留）；pytest 141 项全部通过</li>
            </ul>
          </div>

                    <!-- V3.1.06 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.06</span>
              <span class="version-date">2026-08-19</span>
            </div>
            <ul class="version-changes">
              <!-- xuechong 2026-08-19 研发BUG-0027-图档扫描-3.1.06-票据单据区分判定逻辑优化 更新说明 -->
              <li>【BUG修复】票据/单据判定误伤表格文档：含彩色印刷条带的普通表格（饱和度区域≥5%）被误判为单据模式，纸张边界检测又把密集印刷的表格区并入单据保护，导致表格底色（250-254）与刷白的外部背景（255）出现肉眼可见色差。新增纸张边界与彩色区域重叠校验：真票据纸界与彩域是同一张纸（实测重叠率≥99.7%），重叠率低于 10% 判定为误判，拒绝并入并回退普通文档模式（实测问题样张重叠率为 0）</li>
              <li>【优化】黑白打印单据背景白化兜底：单据纸内整体底色近白（中位饱和度<20 且彩域占比<30%）时，纸内接近底色的未保护像素统一白化，消除纸内外色差；彩色底票据（黄/粉/绿纸）双重条件拦截，行为与旧版完全一致，可用 RECEIPT_NEARWHITE_WHITEN 开关整体关闭</li>
              <li>【测试】新增 BUG-0027 验收测试：问题样张色差块 17→0、票据样张逐像素零回退、普通文档样张（含 BUG-0026 客户 5 张）逐像素零变化守卫</li>
            </ul>
          </div>

          <!-- V3.1.05 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.05</span>
              <span class="version-date">2026-08-18</span>
            </div>
            <ul class="version-changes">
              <li>【BUG修复】图片转PDF/一键修图净化后残留灰色背景、灰色方块：灰色保护 Layer1.5 碎片聚合在正常白底文档上生成覆盖全页的虚假保护掩码（实测占页面 23%~69%），阻断背景白化。新增总开关默认关闭（ENABLE_GRAY_CLUSTER_L15），正常文档净化干净度恢复老版水平，图纸实心灰色内容仍由 Layer1/Layer2 完整保护</li>
              <li>【BUG修复】高白图片散点灰噪清理误伤灰色保护区：散点清理增加灰色保护区排除，修复图纸灰矩形在保守白化路径下被误刷白的问题</li>
              <li>【净化实测】客户样张灰色方块面积降至老版 3.0.3 水平（最差样张 14.4 万降至 0.9 万像素），表格单元格区不再发灰</li>
            </ul>
          </div>

                    <!-- V3.1.04 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.04</span>
              <span class="version-date">2026-08-17</span>
            </div>
            <ul class="version-changes">
              <li>【环境加固】Windows 启动环境隔离：服务只认项目 .venv 虚拟环境，缺失时自动重建（种子 Python 按固定探测顺序定位并验证版本），彻底杜绝外部软件污染 PATH 导致误用其他 Python</li>
              <li>【BUG修复】一键修图 TIFF 崩溃（cannot unpack non-iterable numpy.int32）：OpenCV 5 的 HoughLinesP 返回结构从 (N,1,4) 改为 (N,4)，倾斜检测两处解包改为双版本兼容写法</li>
              <li>【依赖加固】stringzilla 钉死 5.1.1（5.1.2+ 无 Windows cp311 预编译 wheel 会导致安装失败）；显式约束 opencv-python 版本上限，防止依赖大版本漂移引发运行时异常</li>
              <li>【优化】版本号统一 X.X.XX 两位小数格式（历史版本 3.1.3→3.1.03 等）</li>
            </ul>
          </div>

          <!-- V3.1.03 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.03</span>
              <span class="version-date">2026-08-07</span>
            </div>
            <ul class="version-changes">
              <li>【性能优化】灰色内容保护向量化重写：Python 逐连通域循环改为 NumPy 全图向量化，复杂度从 O(连通域数×图像像素) 降至 O(图像像素)，单张 300DPI 清洁耗时从约 60s 降至约 5s（灰色保护阶段 58s→2s）</li>
              <li>【性能优化】页面方向检测加速：det+cls 快速检测替代 4 次 det+rec，方向检测耗时从约 1.3s 降至约 0.3s</li>
              <li>【性能优化】OCR 引擎统一预热 det960，消除多引擎并存导致的显存重复占用和冷启动延迟</li>
              <li>【性能优化】GPU 并发控制从全局 Lock 升级为 BoundedSemaphore（可配置并发许可数），支持多页并行处理</li>
              <li>【性能优化】双层 PDF 生成优化：单页快速文字层预初始化 + 内存流合并 PDF，减少磁盘 I/O</li>
              <li>【性能优化】debug 可视化拷贝条件化：仅 debug 模式拷贝 vis 图，生产环境零开销</li>
              <li>【BUG修复】性能优化引入的彩色内容被灰度化问题：向量化 Step2 恢复彩色通道保护逻辑</li>
              <li>【BUG修复】灰色区间保护回归：背景白化误删灰色工程图纸内容，修复灰色阈值区间判断</li>
              <li>【BUG修复】灰色保护 L1.5 小碎片空间聚合回归：向量化后聚合逻辑丢失，恢复空间邻近聚合</li>
              <li>【BUG修复】页面方向 Phase 2 旋转映射反向：导致部分票据（如 011-019）上下颠倒</li>
              <li>【BUG修复】票据外部彩色噪点未清理：印章/彩色保护掩码全局检测溢出票据边界，限制保护掩码于票据区域+小边距内</li>
              <li>【BUG修复】批量一键修图完成后不自动跳转 PDF 生成步骤：递归批量修图完成后面板未切换</li>
              <li>【BUG修复】PDF 页面尺寸 DPI 丢失：生成 PDF 时传入原始 DPI 确保页面尺寸正确</li>
              <li>【BUG修复】OCR 引擎三层验证健壮性：包级→列表级→运行级失败自动回退 CPU，不再中断流程</li>
              <li>【BUG修复】灰色内容保护精度提升：新增面积上限过滤（防大块浅灰背景被保护）、深灰纹理判定、Layer2.5 灰色内容保护通道、Layer3 膨胀收窄</li>
              <li>【优化】登录锁定时间从 300 秒缩短至 10 秒（5 次失败后）</li>
              <li>【优化】首次启动自动生成管理员口令，支持环境变量覆盖</li>
            </ul>
          </div>

                    <!-- V3.1.02 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.02</span>
              <span class="version-date">2026-07-30</span>
            </div>
            <ul class="version-changes">
              <li>【优化】图片转PDF性能优化：直接解码嵌入图像跳过页面重渲染，减少不必要的GPU缓存清理频率</li>
              <li>【优化】内存流传递JPEG避免临时文件的磁盘写入+读取+删除</li>
              <li>【优化】跳过冗余的双层PDF转换：每页已生成OCR文字层，合并时完整保留</li>
              <li>【优化】GPU队列锁保护防止多用户并发导致显存竞争OOM</li>
            </ul>
          </div>

          <!-- V3.1.01 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.01</span>
              <span class="version-date">2026-07-25</span>
            </div>
            <ul class="version-changes">
              <li>【BUG修复】工程图纸灰色内容四层渐进保护：L1大面积连通域 + L1.5小碎片空间聚合 + L2几何规则性 + L3边缘缓冲</li>
              <li>【BUG修复】剖面线/交叉线区域识别：闭运算聚合密集小碎片，填充外接矩形保护完整灰色矩形</li>
              <li>【BUG修复】单据模式印章/彩色保护始终执行（不依赖 paper_boundary_used），骑缝章不再被擦除</li>
              <li>【BUG修复】前端手动模式步骤面板状态机修复（handleStepClick + restoreTaskState）</li>
              <li>【BUG修复】活跃任务关闭持久化到 localStorage，下次打开不再弹出</li>
              <li>【BUG修复】同名不同扩展名图片 PDF 覆盖问题修复</li>
              <li>【BUG修复】JWT 密钥持久化到文件（.jwt_secret），服务重启后用户无需重新登录</li>
              <li>【BUG修复】401 拦截器 token 刷新失败时正确清除登录状态并跳转登录页</li>
              <li>【优化】灰色内容保护支持配置开关 ENABLE_GRAY_CONTENT_PROTECTION，可一键禁用</li>
            </ul>
          </div>

          <!-- V3.1.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.1.00</span>
              <span class="version-date">2026-07-21</span>
            </div>
            <ul class="version-changes">
              <li>【用户隔离】API 端点全面加固：upload.py task_id 穿越防护、edit_pdf.py scope 注入、directory.py 目录权限校验、tasks.py 临时目录隔离、system.py 管理员角色校验</li>
              <li>【安全加固】edit_pdf.py 跨用户导入漏洞修复：移除危险的路径回退逻辑，确保用户只能访问自己的数据</li>
              <li>【安全加固】directory.py 路径校验修复：有用户时仅允许 scope 目录范围内的操作，batch/convert 路径严格校验</li>
              <li>【认证修复】密码哈希双格式兼容：verify_password 同时支持新版 PBKDF2 和旧版 SHA-256，登录时透明升级，用户无感知</li>
              <li>【认证修复】SPA 路由直接访问修复：认证中间件仅拦截 /api/ 路径，前端路由（/login、/img-to-pdf 等）放行；StaticFiles 添加 SPA fallback 返回 index.html</li>
              <li>【认证修复】密码迁移策略优化：_migrate_passwords 不再强制重置旧密码为 admin123，改为登录时透明升级</li>
              <li>【测试】250+ 项安全测试覆盖：user_isolation + security + smoke 全量回归通过</li>
            </ul>
          </div>

          <!-- V3.0.03 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.0.03</span>
              <span class="version-date">2026-07-03</span>
            </div>
            <ul class="version-changes">
              <li>【BUG修复】一键修图轮询 Network Error：后端 batch_clean_images_task 改为 async，CPU 密集操作（cv2.imdecode / cleaner.process / save_image）用 run_in_executor 线程池执行，释放 GIL 避免阻塞事件循环导致轮询超时</li>
              <li>【BUG修复】前端7个轮询循环增加网络错误重试机制（连续3次失败才停止+弹框），单次瞬时网络抖动不再中断轮询；轮询间隔从500ms调整为5000ms降低服务器压力</li>
              <li>【流程加固】CLAUDE.md 新增强制规则：修改前端源码后必须立即重建 dist；start.bat 去掉 --silent 让构建错误可见；start.sh 新增前端自动构建（node 可用时自动 npm install + build，源码比 dist 新时自动重建）</li>
              <li>【测试】修复 test_api.py 版本号比较值（更新脚本遗漏导致1项测试失败）</li>
            </ul>
          </div>

                    <!-- V3.0.02 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.0.02</span>
              <span class="version-date">2026-06-30</span>
            </div>
            <ul class="version-changes">
              <li>【BUG修复】转换记录弹框下载/预览按钮对应错误PDF：统一使用 state.download_history 筛选逻辑</li>
              <li>【BUG修复】编辑按钮导入失败(400)：修复 edit-pdf/import 端点使用正确的数据源</li>
              <li>【BUG修复】历史记录 API 返回旧数据兼容：补全缺失的 username 字段</li>
              <li>【优化】删除转换记录弹框序号列</li>
              <li>【优化】预览端点添加缓存控制头，防止浏览器缓存旧结果</li>
              <li>【优化】统一 COLOR_RECEIPT_THRESHOLD 默认值为 0.15 (15%)</li>
              <li>【优化】run_tests.py 修复 Windows GBK 编码崩溃 + 增强诊断输出</li>
              <li>【测试】新增 test_history_api_consistency.py 测试用例（6项）</li>
            </ul>
          </div>

          <!-- V3.0.01 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.0.01</span>
              <span class="version-date">2026-06-27</span>
            </div>
            <ul class="version-changes">
              <li>【兼容修复】HTTP IP 非安全上下文适配：crypto.subtle（纯JS SHA-256降级）、navigator.clipboard（execCommand降级）</li>
              <li>【兼容修复】CORS 配置支持从 url.conf 读取 DOCSTUDIO_CORS_ORIGINS</li>
              <li>【认证安全】去掉兼容模式：无 token 直接返回 401，不再允许未登录访问</li>
              <li>【数据架构】下载/上传/编辑/双层 四类历史记录统一按 username 字段做用户隔离：同一列表 + 写入标记 + 读取筛选</li>
              <li>【数据迁移】旧记录自动补 username=admin，新记录写入当前用户真实 username</li>
              <li>【bat 修复】所有 .bat 文件 CRLF 行尾 + chcp 65001 + 中文注释英文化</li>
              <li>【UI 优化】登录错误提示改为红色醒目样式 + 抖动动画</li>
              <li>【版本号】LoginPage.vue 补入版本号升级清单</li>
            </ul>
          </div>

          <!-- V3.0.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V3.0.00</span>
              <span class="version-date">2026-06-03</span>
            </div>
            <ul class="version-changes">
              <li>【多用户系统】全新多用户认证架构：JWT + PBKDF2 + Bearer Token 中间件 + 用户注册/登录/管理 API</li>
              <li>【数据隔离】按 user_id 隔离全部目录和历史记录，管理员可管理所有用户，旧数据自动迁移</li>
              <li>【上传取消】前端 AbortController + 后端取消标志 + 弹窗取消按钮 + 临时文件清理</li>
              <li>【上传记录】上传历史系统：自动记录/实时更新/查看/删除/继续处理</li>
              <li>【状态恢复】sessionStorage + 活跃任务 API + onMounted 自动恢复文件列表和处理状态</li>
              <li>【上传弹窗】模态进度对话框：文件夹名/文件数/进度条/当前文件名/已用时间</li>
              <li>【登录页】独立 /login 页面，每次访问必先登录；UserBadge 全站显示当前用户</li>
              <li>【用户管理】管理员弹窗：查看列表/创建用户/重置密码/删除用户</li>
              <li>【构建树修复】修复子目录被过滤导致文件树为空的 bug</li>
              <li>【GPU 队列】GPU 任务串行化锁，防多用户并发 OOM</li>
              <li>【已知问题】HTTP IP 访问时 crypto.subtle 不可用导致登录失败（已在 V3.0.01 修复）</li>
            </ul>
          </div>

          <!-- V2.3.08 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.08</span>
              <span class="version-date">2026-06-01</span>
            </div>
            <ul class="version-changes">
              <li>【边缘杂质检测】新增 _detect_edge_impurity_strips 独立检测函数，基于5条标准（非票据、紧贴图片边缘、连续但不太长、周围有空白间隙、黑色非印章）精准清除四边扫描阴影/黑边，结果不受 YOLO/frame 保护掩码清除</li>
              <li>【票据修复】黄色票据一键修图被擦除：_process_receipt_document 中饱和度mask与纸张边界从"替换"改为"并集"，防止不准确的纸张边界缩小保护区域导致黄色票据内容被刷白（黄色保留率 52%→100%）</li>
              <li>【票据修复】彩色票据检测漏判：_detect_color_receipt 新增饱和度中位数回退检测，解决高亮票据因 V 值偏高导致 S+V 检测严重低估彩色像素占比的漏判问题</li>
              <li>【边缘检测】_detect_edge_columns 重写：从单一的左右边缘列扫描升级为四边全覆盖 + 多段 frame_line strip 检测 + 间隙判断，支持同一边缘存在多段分离暗色带的场景</li>
              <li>【边缘检测】_detect_frame_lines 新增边缘杂质排除（在 dilation 之后执行），防止框线保护与边缘杂质检测冲突导致 edge_mask 被清除</li>
              <li>【散点清理】四边边缘新增散点杂质清理：3%图高/宽范围内的稀疏暗像素（密度&lt;10%）自动清除，解决文档边缘过渡区的散点扫描噪点</li>
              <li>【参数优化】EDGE_IMPURITY_SEAL_S_THRESHOLD 从 30 调整到 50，避免扫描色偏导致的暗像素饱和度偏高被误判为印章</li>
            </ul>
          </div>

          <!-- V2.3.07 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.07</span>
              <span class="version-date">2026-05-31</span>
            </div>
            <ul class="version-changes">
              <li>【架构重构】app.py 路由拆分：单体架构拆分为 10 个独立路由模块（routes/auth.py、directory.py、download_history.py、dual_layer.py、edit_pdf.py、files.py、system.py、tasks.py、upload.py、websocket.py），main app.py 从 6400+ 行精简至约 1873 行</li>
              <li>【架构重构】新增 services/ 服务层包：app_state（全局状态管理）、history_service（历史记录持久化）、image_utils（图像工具）、logging_service（日志服务）、path_service（路径管理）、ws_service（WebSocket管理），全局可变状态统一通过 state.* 命名空间访问</li>
              <li>【架构重构】源码从扁平 backend/ 目录迁移为标准 Python 包 document_scanner/（含 __init__.py、__main__.py），新增 pyproject.toml 标准 PEP 621 项目配置</li>
              <li>【代码清理】PaddleOCR 死代码清理：移除 _ocr_engine、get_ocr_engine()、parse_ocr_result()、ocr_pdf_to_searchable() 等约 230 行未使用代码</li>
              <li>【代码清理】cleaner.py 函数命名统一：移除 _optimized 后缀（9 个函数），CUDA 缓存逻辑简化；删除 image_utils.py 死函数 unify_image_size、resize_for_ocr</li>
              <li>【代码清理】删除旧构建脚本 9 个：build_all.py、build_backend.py、build_cross_platform.py、build_frontend.py、build_package.py、generate_manual.py、batch_template_match.py、example.py、download_torch_whl.ps1/sh</li>
              <li>【代码清理】前端清理：删除 frontend/index.html.bak（2598行残留文件）、TreeNodeNew.vue（已合并到 TreeNode.vue）、task.js store（未使用）</li>
              
              <li>【安全加固】路径穿越防护全面修复：8 处端点添加 resolve() + relative_to() 双重路径校验，防止通过 symlink 或 ../ 绕过访问系统文件</li>
              <li>【安全加固】Decompression Bomb 防护：5 处 Image.open() 前设置 MAX_IMAGE_PIXELS=20000×20000 上限，finally 恢复原值避免拒绝服务攻击</li>
              <li>【安全加固】文件上传大小限制：edit_pdf.py、dual_layer.py、tasks.py 改为分块读取 + 200MB 单文件限制 + Content-Length 预检查，防止内存耗尽攻击</li>
              <li>【安全加固】登录认证全面升级：MD5 三次哈希 → SHA-256 10 万轮哈希 + hmac.compare_digest 常量时间比较（防时序攻击）+ 速率限制（60 秒 5 次，超限封禁 5 分钟）</li>
              <li>【安全加固】set_source_dir / set_target_dir 添加路径安全校验，限制在 STORAGE_ROOT 范围内；CORS 配置收紧为 4 个具体 localhost 地址</li>
              <li>【安全加固】history_service 统一添加 f.flush() + os.fsync()，防止崩溃导致数据丢失；app.py 新增全局异常捕获处理器</li>
              <li>【目录调整】前端 HomePage.vue 从 src/ 迁移到 src/pages/，测试文件 37 个调试脚本归入 tests/debug/ 子目录</li>
              <li>【文档规范】CLAUDE.md 新增"版本号升级检查清单"（17 项逐条勾销 + sed 一键替换命令），杜绝版本号更新遗漏</li>
              <li>【文档规范】CLAUDE.md 及三个编码规范 SKILL 新增注释规范（强制）：Python 使用 # xuechong YYYY-MM-DD，JS/Vue 使用 // xuechong YYYY-MM-DD</li>
              <li>【文档规范】10 个 SKILL 文件全面审查更新：修正核心文件行数、函数签名、路径引用、认证算法描述等 30+ 处过时内容</li>
              <li>【其他】默认登录口令更新；start.bat 合并后台运行 + 自动打开浏览器功能</li>
              <li>【体验优化】浏览器缓存防护：后端添加 Cache-Control 响应头中间件（index.html 禁止缓存，静态资源允许长期缓存）；前端版本自动检测（每 30 秒轮询 API，发现版本不一致自动硬刷新），彻底解决新版本发布后浏览器缓存旧文件导致 404 的问题</li>
              <li>【项目清理】删除项目根目录字面量 ${DOCSTUDIO_BASE_DIR} 垃圾目录；清理 .claude/docs/ 下 13 个与 docs/ 重复的文件；docs/ 目录整体迁移到 .claude/docs/，根目录保持清洁；补充 .gitignore 缺失项</li>
            </ul>
          </div>

          <!-- V2.3.06 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.06</span>
              <span class="version-date">2026-05-20</span>
            </div>
            <ul class="version-changes">
              <li>修复程序包升级后历史操作记录丢失问题：url.conf 纳入程序包，所有路径由 url.conf 统一配置</li>
              <li>统一磁盘目录结构：程序包 crabapple-docstudio-v{版本号} + 持久化数据目录 /data/crabapple-docstudio</li>
              <li>依赖包目录从 crabapple-docstudio-deps 改为 /data/crabapple-docstudio/dependence/</li>
              <li>修复 config.py、start.sh、ocr 模块等 7 处不安全的路径回退默认值，全部指向持久化目录</li>
              <li>新增启动诊断日志：输出 url.conf 加载来源和 DATA_DIR 实际路径</li>
              <li>修复 start.sh 中 url.conf 加载时机：提前至所有依赖查找之前，避免 BASE_DIR 为空</li>
            </ul>
          </div>

          <!-- V2.3.05 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.05</span>
              <span class="version-date">2026-05-18</span>
            </div>
            <ul class="version-changes">
              <li>新增基于纸张亮度的票据边界检测算法（大尺度模糊 + Otsu 阈值），解决饱和度方法无法检测白色/浅色票据纸张边界的问题</li>
              <li>修复票据四周扫描杂质（黑线、污渍、曝光）无法清除的问题：三条处理路径（小票据/彩色票据/普通文档）全部优先使用纸张亮度方法，自动回退原有方法</li>
              <li>修复路径A（小票据贴A4纸模式）内容保护过于激进导致票据外黑线被误保护为"文字"的问题：纸张方法成功时跳过内容保护</li>
              <li>票据边界向外多保留2像素（BOUNDARY_MARGIN_ADJUST），避免边缘内容被过度切除</li>
              <li>修复 DocumentCleaner 缺少 self.config 属性导致普通文档路径 AttributeError 崩溃</li>
              <li>一键修图预览实时更新优化：子目录递归修图时每完成一张图片立即刷新修图区预览（修复之前预览完全不更新的问题）</li>
              <li>一键修图轮询触发机制从 current_path 字符串比对改为 processed_files 计数递增，避免快速处理时漏更新</li>
              <li>修复修图区 canvas 覆层导致图片视觉粗糙：关闭 canvas 图像平滑渲染</li>
              <li>修图区边框样式优化：原图区/修图区边框从 1px dashed 改为 1px solid 实线，分隔线从虚线改为实线</li>
              <li>修图区底部增加 8px 额外间距，避免下边框被截断</li>
            </ul>
          </div>

          <!-- V2.3.04 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.04</span>
              <span class="version-date">2026-05-17</span>
            </div>
            <ul class="version-changes">
              <li>修复密集表格票据（如增值税发票、物流验收单）一键修图后仍存在轻微倾斜的问题：霍夫变换被表格长线误导产生假倾斜角（+3°），导致反向过度纠偏</li>
              <li>新增投影法倾斜检测（_detect_skew_by_projection）：基于全图灰度水平投影方差，不受表格竖线干扰</li>
              <li>新增投影法最终裁决机制：当霍夫检测角度 >1° 但投影法认为图像已正（<1.5°）时，以投影法为准放弃纠偏，避免过度纠正</li>
              <li>修复饱和度霍夫与灰度霍夫交叉验证过于激进的问题：灰度霍夫高置信（样本量 ≥50 且标准差 <2°）时信任灰度结果</li>
              <li>修复霍夫高离散度（std>5°）时无有效回退的问题：全部方法失效时自动回退到投影法兜底</li>
            </ul>
          </div>

          <!-- V2.3.03 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.03</span>
              <span class="version-date">2026-05-16</span>
            </div>
            <ul class="version-changes">
              <li>修复手动模式下多文件夹批处理仅处理第一个文件夹的问题（根因：点击目录时自动递归选中第一张图片预览导致 selectedPath 意外改变，批处理目标变成叶子目录）</li>
              <li>修复文件树点击目录节点同时触发展开和选中的耦合问题：展开/收起改为仅由 ▶ 图标独立控制，避免浏览文件夹树时无意改变批处理目标</li>
              <li>修复批处理完成后单一"下载PDF"按钮误导问题：批处理生成多个PDF时不显示主下载按钮，改为引导用户通过"转换记录"分别下载各文件夹PDF</li>
              <li>修复后端 process_uploaded_folder_task 竞态条件：下载历史记录移到 status="completed" 之前写入，使用局部变量而非 task["merged_pdf"]，避免下一目录的 processUpload 重置字段导致历史 PDF 路径为空</li>
              <li>修复 upload_folder 端点未归一化 Windows 反斜杠路径的问题</li>
              <li>部署架构文档更新为三环境分工（WSL编码 → Windows测试 → openEuler生产）</li>
            </ul>
          </div>

          <!-- V2.3.02 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.02</span>
              <span class="version-date">2026-05-10</span>
            </div>
            <ul class="version-changes">
              <li>新增图片转PDF转换记录编辑跳转功能：转换记录弹框中每个记录新增"编辑"按钮，点击可将该PDF导入编辑PDF模块进行编辑修改</li>
              <li>新增编辑PDF模块返回图片转PDF按钮：从图片转PDF模块进入编辑PDF时，右上角显示"← 返回图片转PDF"按钮，点击回到图片转PDF页面</li>
              <li>新增转换记录编辑状态跟踪：已编辑的记录显示"已编辑"标记，编辑后的下载次数独立统计</li>
              <li>修复图片转PDF模块转换记录弹框中点击编辑按钮后弹框不关闭的问题</li>
              <li>修复编辑PDF模块 keep-alive 双初始化（onMounted + onActivated）竞态导致返回按钮错误显示"返回首页"的问题</li>
            </ul>
          </div>

          <!-- V2.3.01 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.01</span>
              <span class="version-date">2026-05-09</span>
            </div>
            <ul class="version-changes">
              <li>修复倾斜矫正对防伪图案票据误矫正问题：灰度霍夫检测被支票/汇票等防伪底纹干扰产生虚假倾斜角，导致本已方正的文档被错误旋转</li>
              <li>新增饱和度通道霍夫检测：彩色文档（饱和度均值>10）额外在HSV饱和度通道做Canny+Hough检测，利用文档颜色边界（粉色底 vs 白色扫描仪背景）消除图案干扰</li>
              <li>新增三通道交叉验证决策：灰度霍夫、饱和度霍夫、文字行三通道结果相互校验，灰度与饱和度不一致（差>3°）时标记灰度结果不可靠并放弃矫正，避免误引入倾斜</li>
              <li>倾斜矫正决策强化：文字行为0°且灰度与饱和度一致时，信任霍夫检测结果（修复文字行检测被防伪图案伪装为0°的漏洞）</li>
              <li>磁盘路径 Windows/Linux 完全隔离：url.conf 新增 _WIN 后缀变量区分平台，打包脚本读取 Windows 路径，生产环境读取 Linux 路径，互不干扰</li>
              <li>config.py 新增 sys.platform 平台识别：Windows 自动使用 _WIN 变量，Linux 使用同名变量</li>
              <li>新增 bin/_paths.bat 共享路径模块：所有 bat 脚本统一通过 call 加载路径配置，消除重复代码和不一致默认值</li>
              <li>start.bat 合并后台运行+自动打开浏览器功能（原智能文档扫描.bat），删除冗余启动脚本</li>
              <li>修复 start.bat DOCSTUDIO_DATA_DIR 回退值 shared_data 导致 data\data\ 嵌套目录结构 bug</li>
              <li>打包日志输出全部使用绝对路径（带盘符）</li>
              <li>pack_release.py / pack_deps.py 路径常量改为从 url.conf _WIN 变量读取，不再硬编码</li>
            </ul>
          </div>

          <!-- V2.3.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.3.00</span>
              <span class="version-date">2026-04-22</span>
            </div>
            <ul class="version-changes">
              <li>首页移除"转双层PDF"入口卡片：功能已合并至编辑PDF模块（通过导入已有PDF实现），保留路由兼容旧链接</li>
              <li>编辑PDF模块：保存修改/一键修图后立即生成最终双层PDF（不再延迟到下载时），操作记录面板实时更新</li>
              <li>编辑PDF模块：每次对同一PDF执行一键修图或保存修改时，操作记录的保存时间自动更新为最新时间</li>
              <li>编辑PDF模块：点击返回首页后页面状态通过 keep-alive 保留，下次进入编辑PDF模块恢复到之前的工作状态</li>
              <li>编辑PDF模块：新增OCR语言选择（中文/英文/繁体/日文/韩文），保存页面和一键修图均使用所选语言</li>
              <li>编辑PDF模块：一键修图完成后自动写入操作记录，显示全局Loading遮罩</li>
              <li>编辑PDF模块：预览区（原图区/修图区）样式与图片转PDF模块完全对齐，使用统一的 itp-preview 全局样式</li>
              <li>编辑PDF模块：修复保存为JPEG格式但文件扩展名为PNG的格式不一致问题，统一改为PNG格式保存</li>
              <li>编辑PDF模块：修复修图区显示两张图片的bug（inline transform 覆盖了 CSS 居中定位）</li>
              <li>编辑PDF模块：操作记录在保存页面时即写入（不再仅在下载时写入），支持从图片转PDF和转双层PDF导入后正确记录</li>
              <li>图片转PDF模块：手动模式批量一键修图完成后弹出确认弹窗（"是否开始生成PDF？"），点击确定自动切换到生成PDF页面并开始生成</li>
              <li>修复上传文件夹进度条不精确：点击上传后进度条立即显示100%的问题，改为基于 axios onUploadProgress 反映真实网络上传进度</li>
              <li>上传进度条新增 loading 旋转动画，上传阶段实时显示百分比和已上传文件数</li>
              <li>上传100%后提示"服务器处理中"，避免用户误以为卡住</li>
              <li>点击目录时自动递归查找第一张图片并预览，D区工具栏和E区预览区即时可用</li>
              <li>修复批量一键修图完成后卡在loading页面的问题：后端任务完成时未设置 completed 状态</li>
              <li>全系统Loading样式统一：ImageToPdfPage、EditPdfPage、PreviewPanel等所有Loading使用全局 global-loading 样式，蒙版背景完全透明</li>
              <li>修复编辑PDF服务端 NameError：forward reference（init_edit_pdf_history_file 定义在调用之后）和 task_info 未赋值</li>
              <li>修复编辑PDF模块多个严重逻辑bug：合并PDF缓存导致后续编辑丢失、文件句柄资源泄漏、OCR状态值不一致、img_bgr未做None检查、JSON null值导致strip()崩溃</li>
              <li>编辑PDF模块异常处理全面加固：所有异常路径记录详细参数（task_id、file_id、页码、文件路径），通知前端并停止任务</li>
              <li>新增编辑PDF操作记录全面自动化测试（AST静态分析 + 48项测试覆盖）</li>
            </ul>
          </div>

          <!-- V2.2.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.2.00</span>
              <span class="version-date">2026-04-17</span>
            </div>
            <ul class="version-changes">
              <li>升级 CUDA 12.8 + PyTorch 2.8.0，原生支持 RTX 5070 (sm_120 / Blackwell 架构)</li>
              <li>全局异常捕获机制：任何处理异常自动记录完整堆栈日志，前端弹框持续显示</li>
              <li>异常即停策略：自动处理、批量修图、批量重绘中遇到异常立即停止当前任务，不再静默跳过</li>
              <li>GPU 错误自动恢复：CUDA 异常后自动清理显存缓存，YOLO 推理失败自动回退 CPU</li>
              <li>修复 RapidOCR PosixPath 类型错误（omegaconf 不支持 Path 对象）</li>
              <li>修复 PyMuPDF 线程安全问题：多页PDF并行OCR时每个线程独立打开文档，避免跨线程共享导致崩溃</li>
              <li>批量处理时每5张图片自动清理 GPU 显存缓存，防止显存持续增长导致 OOM</li>
              <li>统一双层PDF转换失败行为：失败时保留原PDF并继续完成任务，不再中断整个流程</li>
              <li>所有异常路径统一记录完整 traceback 到日志和前端通知，不再静默忽略</li>
              <li>修复 sync_log 线程安全问题：日志列表操作加锁，异步推送改用 run_coroutine_threadsafe</li>
              <li>限制双层PDF转换线程池为4线程（原默认32线程），防止线程爆炸</li>
              <li>双层PDF转换API响应新增 success 布尔字段，前端可准确判断转换结果</li>
              <li>修复 ConfigCache 配置默认值与 config.py 不一致（PUNCH_HOLE_MAX_ASPECT 5.0→8.0）</li>
              <li>修复 ocr_pdf.py 临时目录泄漏：方向矫正失败时自动清理临时文件</li>
              <li>BOUNDARY_DEBUG_PATH 改为跨平台路径（不再硬编码 Windows d:/temp）</li>
              <li>修复 ConfigCache 全部6项默认值与 config.py 不一致（ENABLE_CREASE_DETECTION、PUNCH_HOLE_FULL_IMAGE 等）</li>
              <li>修复 ocr_rapid.py 备份配置类默认值不一致（OCR_DET_LIMIT_SIDE_LEN 1920→800）</li>
              <li>修复 ocr_rapid.py 缓存目录硬编码 Windows 路径，改为跨平台（$HOME/crabapple-docstudio/cache/）</li>
              <li>修复 cleaner.py 方向检测并行 OCR 线程安全问题：onnxruntime CUDA EP 不支持多线程并发，改为串行执行</li>
              <li>修复 WebSocket 连接泄漏：异常断开时主动从 active_connections 移除</li>
              <li>应用关闭时清理线程池资源（shutdown_event 中关闭 _dual_layer_executor）</li>
              <li>清理 ocr_rapid.py 死代码（未使用的 _process_single_page 函数）和冗余导入</li>
              <li>修复 config.py Linux 默认存储路径 /data1/ 改为 ~/crabapple-docstudio，与 start_server.py 和 start.sh 保持一致</li>
              <li>修复 app.py 编辑PDF保存后OCR读取图片使用 cv2.imread 不支持中文路径，改为 np.fromfile + cv2.imdecode</li>
              <li>修复 ocr_pdf.py 双层PDF中文字体回退从 Helvetica（不支持中文）改为 china-s</li>
              <li>修复 cleaner.py 缓存目录硬编码 Windows 路径，改为跨平台（$HOME/crabapple-docstudio/cache/）</li>
              <li>修复 pack_release.py 生成脚本中 LD_LIBRARY_PATH 包含不存在的 CUDA 13.x 路径，移除并优先 CUDA 12.8</li>
              <li>修复 ocr_rapid.py OCR_DET_LIMIT_SIDE_LEN 备份值 800 改回 1920，确保手写小字和密集表格检测精度</li>
              <li>修复多页PDF并行OCR导致 GPU 显存 OOM：GPU 模式下 onnxruntime CUDA EP 改为串行推理，CPU 模式保留多线程</li>
            </ul>
          </div>

          <!-- V2.1.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.1.00</span>
              <span class="version-date">2026-03-27</span>
            </div>
            <ul class="version-changes">
              <li> 新增图片重绘功能：强化（像素加深）与弱化（像素变浅），支持单张和批量操作</li>
              <li> 重绘纯白像素保护：纯白背景像素（#FFFFFF）不受强化/弱化影响，仅调整非纯白像素</li>
              <li> 新增重绘设置弹窗：可配置调整步长（1-50像素值），默认步长10</li>
              <li> 批量重绘后台任务：支持子目录批量处理，实时进度条+耗时统计</li>
              <li> 重绘操作支持撤销/重做，操作前自动备份原图</li>
              <li> 重绘工具集成于D区工具栏"图片重绘"下拉菜单，导入和修图步骤均可使用</li>
            </ul>
          </div>

          <!-- V2.0.00 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V2.0.00</span>
              <span class="version-date">2026-03-26</span>
            </div>
            <ul class="version-changes">
              <li> 前端架构重构：5700行单体App.vue拆分为模块化组件、页面、路由结构</li>
              <li> 新增Vue Router路由：图片转PDF、编辑PDF、转双层PDF三大功能独立页面</li>
              <li> 新增自动模式：无人值守全自动流程（修图→OCR→生成PDF），支持子目录批量处理</li>
              <li> 步骤化工作流：进度条引导（导入→修图→生成PDF），支持步骤间自由切换</li>
              <li> 新增左侧文件管理栏：文件树浏览、目录展开/折叠、上传进度展示</li>
              <li> 新增图片修图工具：旋转、橡皮擦手绘、撤销/重做、一键还原</li>
              <li> 新增操作记录：历史PDF下载记录、预览、删除管理</li>
              <li> 新增Toast通知系统，替代原生弹窗提示</li>
              <li> UI配色优化：统一为橙+蓝双强调色，移除紫色、简化渐变</li>
              <li> 自动模式交互管控：精确禁用非必要控件，仅保留上传/模式切换/顶栏按钮可操作</li>
            </ul>
          </div>

          <!-- V1.5.04 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V1.5.04</span>
              <span class="version-date">2026-03-18</span>
            </div>
            <ul class="version-changes">
              <li>大半径扫描算法：DPI自适应半径缩放，不同分辨率图像清洁效果一致</li>
              <li>空间网格优化：文字块孤立检测算法从O(n²)优化为O(n)，处理速度大幅提升</li>
              <li>新增文字块孤立半径配置（TEXT_BLOB_ISOLATION_RADIUS），精细控制清洁范围</li>
              <li>形态学操作核尺寸随DPI自动缩放，高分辨率扫描件处理更精准</li>
            </ul>
          </div>

          <!-- V1.5.03 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V1.5.03</span>
              <span class="version-date">2026-02-01</span>
            </div>
            <ul class="version-changes">
              <li>修复图片转PDF质量严重下降的问题（TIF内部JPEG压缩检测）</li>
              <li>智能污渍清除：自动清除扫描阴影、纸张老化等灰色污渍</li>
              <li>背景纯白优化：接近白色的背景(#FEFEFE)自动转为纯白(#FFFFFF)</li>
              <li>彩色票据保护：边界检测失败时智能判断，避免内容被误删</li>
              <li>彩色检测优化：使用更严格的饱和度阈值，避免灰色污渍被误判为彩色</li>
            </ul>
          </div>

          <!-- V1.5.02 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V1.5.02</span>
              <span class="version-date">2026-01-30</span>
            </div>
            <ul class="version-changes">
              <li>倾斜矫正算法优化：智能判断霍夫变换结果可靠性，避免噪声干扰</li>
              <li>优先文字行检测：当霍夫变换结果分散时，优先使用文字行检测结果</li>
              <li>修复：部分图片一键修图后反而变歪的问题</li>
              <li>工程结构优化：文档移至docs/目录，脚本移至bin/目录</li>
              <li>版本号展示：浏览器标签页、登录弹框标题均显示当前版本号</li>
            </ul>
          </div>

          <!-- V1.5.01 -->
          <div class="version-item">
            <div class="version-header">
              <span class="version-tag">V1.5.01</span>
              <span class="version-date">2026-01-27</span>
            </div>
            <ul class="version-changes">
              <li>功能重命名：首页"图片转双层PDF"简化为"图片转PDF"</li>
              <li>功能重命名：首页"扫描版PDF转双层PDF"简化为"转双层PDF"</li>
              <li>倾斜矫正增强：改进检测算法，使用文字行方向检测+霍夫变换双重校验</li>
            </ul>
          </div>
        </div>
      </div>
    </div>
  </div>
  </Transition>
</template>

<script setup>
// xuechong 2026-10-09 研发BUG-0071 图标组件：标题 emoji 换单色线性 SVG（版本历史正文不动）
import AppIcon from './AppIcon.vue'

defineProps({
  modelValue: { type: Boolean, default: false }
})

defineEmits(['update:modelValue'])
</script>
