# AWS_RAG
## 痛點
想建立AWS服務，卻屢屢碰上困難，GPT不靈驗，官方文件太多不知從何找起

## 功能簡介
將官方文件使以頁數方式做切片做RAG，取得與問題最相似的內容，提供給GPT做為參考文件後回答。

若有圖片解釋需求，將圖片上傳系統後會自動上傳至GCS並公開(僅有url可讀取)，系統將會依照圖片搭配問題做回覆。

## 前置作業
1. openai api key

2. google cloud 服務帳戶
    - 至 https://console.cloud.google.com/apis/credentials
    - 建立憑證 > 服務帳戶 > (建立完成) >> 金鑰 > 建立新的金鑰(json)

3. 填入 .env 

## 運行方式
<pre><code>bash
$ docker build -t aws_rag .
$ docker run build -p 8000:8000 aws_rag
</code></precode>
