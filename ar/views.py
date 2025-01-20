from django.shortcuts import render
from django.http import JsonResponse
from django.conf import settings
from langchain_community.document_loaders import PyPDFLoader
from langchain_community.vectorstores import FAISS
from langchain.prompts import PromptTemplate
from langchain_openai import OpenAIEmbeddings
from openai import OpenAI
from google.cloud import storage
from opencc import OpenCC
from dotenv import load_dotenv
import os, datetime, uuid, markdown, re


load_dotenv()
os.environ["OPENAI_API_KEY"] = os.getenv("openai")
embeddings = OpenAIEmbeddings()


def generate_embed():
    docs = ["/content/ec2-ug.pdf"]
    all_doc = list()
    for i in docs:
        loader = PyPDFLoader(i)
        documents = loader.load_and_split()
        all_doc = all_doc + documents
        vectorstore = FAISS.from_documents(all_doc, embeddings)
        vectorstore.save_local("embedding")


def image_upload(file_path, file_name):
    client = storage.Client.from_service_account_json('./config/gcs.json')
    bucket = client.get_bucket('awsrag')
    blob = bucket.blob(file_name)  # cloud path
    blob.upload_from_filename(file_path, content_type='image/png')
    # 上傳後一小時內可讀取檔案 (openai可讀取)
    url = blob.generate_signed_url(expiration=datetime.datetime.utcnow() + datetime.timedelta(hours=1))
    return url


def query_knowledge_base(db, query, top_k=2, verbose=1):
    docs_and_scores = db.similarity_search_with_score(query, top_k=top_k)
    try:
        fst_doc, fst_score = docs_and_scores[1]
    except:
        fst_doc, fst_score = docs_and_scores[0]
        
    fst_reference = fst_doc.page_content
    fst_metadata = fst_doc.metadata
    fst_pdf_name = fst_metadata.get("source")
    fst_page_num = fst_metadata.get("page")
    fst_info = {
        "score": fst_score,
        "source": fst_pdf_name,
        "number": fst_page_num,
        "content": fst_reference,
    }
    snd_doc, snd_score = docs_and_scores[0]
    snd_reference = snd_doc.page_content
    snd_metadata = snd_doc.metadata
    snd_pdf_name = snd_metadata.get("source")
    snd_page_num = snd_metadata.get("page")
    snd_info = {
        "score": snd_score,
        "source": snd_pdf_name,
        "number": snd_page_num,
        "content": snd_reference,
    }

    return fst_info, snd_info


def use_prompt_template(fst_info, snd_info, user_query):
    SYS_PROMPT = """
            你是一位專業的雲端架構師，請根據官方文件回答使用者的問題，回答的越詳細越好，
            目標是使用者根據你提供的步驟一個一個完成後即可解決使用者提出的問題。
            
            注意:
                1. 盡可能照著官方文件的步驟呈現完整的範例，避免出現無關緊要的回答，但不要出現參考了哪份檔案之類的字眼。
                2. 若在回答之中有些專有名詞或特殊指令，也給出一些解釋。
            """

    RAG_INFO = f"\n\n第一個參考資訊：{fst_info['content']}; \n第二個參考資訊：{snd_info['content']};\n\n"
    PROMPT = PromptTemplate.from_template("{SYS_PROMPT}{RAG_INFO} \n\n使用者的問題: {QUERY}")
    PROMPT = PROMPT.format(SYS_PROMPT=SYS_PROMPT, RAG_INFO=RAG_INFO, QUERY=user_query)
    return PROMPT


def query_load(user_query):
    db = FAISS.load_local("embedding", embeddings, allow_dangerous_deserialization=True)
    fst_info, snd_info = query_knowledge_base(db, user_query, verbose=2)
    PROMPT = use_prompt_template(fst_info, snd_info, user_query)
    return PROMPT, fst_info, snd_info


def openai_ask(question, url):
    client = OpenAI(api_key=os.getenv("openai"))
    if url:
        model_type = "gpt-4o"
        content = [{"type": "text", "text": question},
                   {
                       "type": "image_url",
                       "image_url": {
                           "url": url
                       }
                   },
                   ]
    else:
        model_type = "gpt-3.5-turbo"
        content = question

    response = client.chat.completions.create(
        model=model_type,
        messages=[
            {
                "role": "user",
                "content": content
            }
        ],
    )
    return response.choices[0].message.content


def main(request):
    user_question = request.POST.get('user_question')
    if user_question:
        user_image = request.FILES.get('user_image')
        cloud_url = None
        
        if user_image:
            file_name = user_image.name + str(uuid.uuid4())
            file_path = os.path.join(settings.MEDIA_ROOT, 'uploads', file_name)

            if not os.path.exists(settings.MEDIA_ROOT + '/uploads'): os.makedirs(settings.MEDIA_ROOT + '/uploads')
            with open(file_path, 'wb+') as destination:
                for chunk in user_image.chunks():
                    destination.write(chunk)
                    
            cloud_url = image_upload(file_path, file_name)

        question, fst_info, snd_info = query_load(user_question)
        cc = OpenCC('s2t')  # 簡轉繁

        ans_rag = cc.convert(openai_ask(question, cloud_url))
        # print(ans_rag)
        ans_normal = cc.convert(openai_ask(user_question, cloud_url))
        # print(ans_normal)

        md = markdown.Markdown(extensions=[
                                "fenced_code",
                                'codehilite',  # 程式碼高亮
                                'tables',  # 支援表格
                                'toc',  # 自動生成目錄
                                'footnotes',  # 支援腳註
        ])
        ans_rag = ans_rag.replace("   - ", '>')
        md_ans_rag = md.convert(ans_rag)
        md_ans_rag = md_ans_rag.replace("<code>", "<pre><code>").replace("</code>", "</code></pre>")
        md_ans_rag = md_ans_rag.replace("&lt;br&gt;", "\n")
        md_ans_rag = md_ans_rag.replace("- <pre><code>", "<pre><code>")
        md_ans_rag = re.sub(r'(^- `)(.*?)`', r'\1\2', md_ans_rag)

        ans_normal = ans_normal.replace("   - ", '>')
        md_ans_normal = md.convert(ans_normal)
        md_ans_normal = md_ans_normal.replace("<code>", "<pre><code>").replace("</code>", "</code></pre>")
        md_ans_normal = md_ans_normal.replace("&lt;br&gt;", "\n")
        md_ans_normal = md_ans_normal.replace("- <pre><code>", "<pre><code>")
        md_ans_normal = re.sub(r'(^- `)(.*?)`', r'\1\2', md_ans_normal)

        return render(request, 'main.html', {'md_ans_rag': md_ans_rag,
                                                                    'md_ans_normal': md_ans_normal
                                                                     })
    else:
        return render(request, 'main.html')
