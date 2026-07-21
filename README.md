# Apple 整修品 MacBook Air M5 Discord 監控器

這個程式每 5 分鐘檢查一次 [Apple 台灣 Mac 整修品](https://www.apple.com/tw/shop/refurbished/mac)。偵測到 **MacBook Air M5** 時，會把完整品名、價格與購買連結傳到你的 Discord 頻道。

程式由你自己 GitHub 帳號中的 GitHub Actions 執行，因此不需要讓電腦一直開機。同一商品持續在架時只通知一次；下架後重新出現才會再次通知。

## 第一步：建立 Discord Webhook

你需要在自己的 Discord 伺服器中擁有「管理 Webhook」權限。

1. 開啟要接收通知的 Discord 文字頻道。
2. 點擊頻道旁的齒輪，進入「整合」→「Webhook」。
3. 選擇「新增 Webhook」，名稱可以填「Apple 整修品監控器」。
4. 確認通知頻道後，點擊「複製 Webhook URL」。
5. 不要把這串網址貼在公開訊息、程式碼或 README；取得這個網址的人可以向該頻道發訊息。

Discord 官方說明：[Intro to Webhooks](https://support.discord.com/hc/en-us/articles/228383668-Intro-to-Webhooks)

## 第二步：放到你的 GitHub 帳號

在 [GitHub 建立新 repository](https://github.com/new)：

- Repository name：例如 `apple-refurbished-m5-monitor`
- Visibility：建議選 **Public**
- 不要勾選自動建立 README、`.gitignore` 或 License，因為此資料夾已經包含這些檔案

接著在這個專案資料夾開啟 PowerShell，依 GitHub 新 repository 頁面顯示的網址執行：

```powershell
git add .
git commit -m "Add Apple refurbished MacBook Air M5 monitor"
git branch -M main
git remote add origin https://github.com/你的帳號/apple-refurbished-m5-monitor.git
git push -u origin main
```

Public repository 中的程式碼會公開，但 Discord Webhook 不會放在程式碼裡。

## 第三步：加入加密 Secret

1. 開啟 GitHub repository。
2. 進入 **Settings** → **Secrets and variables** → **Actions**。
3. 點擊 **New repository secret**。
4. Name 填入 `DISCORD_WEBHOOK_URL`。
5. Secret 貼上剛才複製的 Discord Webhook URL，然後儲存。

## 第四步：測試 Discord 通知

1. 進入 repository 的 **Actions** 頁面。
2. 左側選擇「監控 MacBook Air M5 整修品」。
3. 點擊 **Run workflow**。
4. 勾選「只傳送 Discord 測試通知」，再按綠色的 **Run workflow**。
5. Discord 應在一分鐘左右收到「測試成功」訊息。

## 第五步：啟用監控

GitHub Actions 的定時排程已停用，避免與 Windows 本機監控重複通知。你仍可以在 Actions 頁面手動執行，並取消勾選測試通知，立即檢查 Apple 頁面。

GitHub workflow 保留作為手動測試與備援，不會自行定時執行。

## 本機測試（選用）

需要 Python 3.12 或更新版本：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m pytest
python monitor.py --dry-run
```

若要從本機傳送測試通知，請只在目前 PowerShell 工作階段設定環境變數：

```powershell
$env:DISCORD_WEBHOOK_URL = "貼上你的 Webhook URL"
python monitor.py --test-notification
Remove-Item Env:DISCORD_WEBHOOK_URL
```

不要把 Webhook URL 寫進 `.env` 後提交到 GitHub。

## 運作方式與故障排除

- `state.json` 只記錄目前在架的符合商品編號，用來避免每 5 分鐘重複通知。
- Apple 頁面讀取失敗、頁面結構無法解析或 Discord 傳送失敗時，工作流程會顯示紅色失敗，並保留原本狀態供下次重試。
- 如果 Actions 顯示未設定 `DISCORD_WEBHOOK_URL`，請重新檢查第三步的 Secret 名稱，大小寫必須完全相同。
- 如果 Discord 回傳 401 或 404，通常代表 Webhook 已被刪除或網址不完整，請重新建立並更新 Secret。
- 若不再需要監控，可在 GitHub repository 的 **Actions** 頁面停用 workflow，或直接刪除 repository。

## Windows 本機每分鐘監控

本機監控使用 Windows 工作排程器，每分鐘檢查一次。電腦從睡眠喚醒後，會在下一個週期自動恢復，並啟用「錯過排程後儘快執行」。電腦關機或仍在睡眠時無法檢查。

首次設定時，在 PowerShell 執行：

```powershell
.\setup_windows_task.ps1
```

依提示貼上 Discord Webhook URL。網址會以目前 Windows 使用者的加密金鑰保存於 `.local`，不會提交到 Git。設定程序會先傳送測試通知，成功後才建立排程。

執行紀錄位於 `logs\monitor.log`。若要移除排程：

```powershell
Unregister-ScheduledTask -TaskName "Apple Refurbished Monitor" -Confirm:$false
```
