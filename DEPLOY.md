Evet, **hem Green Agent hem de baseline Purple Agent'ı dockerize etmen gerekiyor.** Kaynaklara göre Phase 1 (Green Agent) aşamasında, benchmark'ın uçtan uca (end-to-end) ve manuel müdahale olmadan çalışabilmesi için tüm bileşenlerin konteynerize edilmiş olması zorunludur.

İşte Green Agent ve baseline Purple Agent'ını AgentBeats standartlarına göre dockerize etmen için izlemen gereken adım adım yol haritası:

### 1. Adım: Baseline Purple Agent'ı Neden Dockerize Etmelisin?
Phase 1 teslimatında, Green Agent'ın (değerlendirici) görevlerini nasıl yerine getirdiğini ve puanladığını göstermek için **en az bir adet A2A uyumlu baseline Purple Agent** sunman zorunludur. Platformun bu testi otomatik olarak (GitHub Actions üzerinden) çalıştırabilmesi için her iki ajanın da bir Docker registry'sinde (Docker Hub, Google Artifact Registry vb.) imaj olarak bulunması gerekir.

### 2. Adım: Proje Yapısını Hazırlama
Her ajan (Green ve Purple) için kök dizinde şu iki kritik dosyayı oluşturmalısın:
*   **run.sh:** Ajanı başlatan betik (Örn: `python main.py run`). Bu dosya `chmod +x run.sh` ile yürütülebilir olmalıdır.
*   **Procfile:** AgentBeats Controller'ı başlatmak için gereklidir. İçeriği şu şekilde olmalıdır: `web: agentbeats run_ctrl`.

### 3. Adım: Dockerfile Oluşturma
Her iki ajan için de (veya tüm sistemi tek imajda topluyorsan o sistem için) bir Dockerfile yazmalısın.
*   **Bağımlılıklar:** `pip install earthshaker` (AgentBeats SDK) ve projenin diğer gereksinimlerini (`requirements.txt`) eklediğinden emin ol.
*   **İpucu:** Google Cloud Buildpacks kullanarak Dockerfile yazmadan da imaj oluşturabilirsin ancak manuel kontrol için standart bir Dockerfile önerilir.

### 4. Adım: İmajları Registry'ye Yükleme
İmajlarını oluşturduktan sonra (build), bunları **herkese açık (public)** bir Docker registry'sine yüklemelisin:
1.  `docker build -t kullanıcı_adı/green-agent:v1 .`
2.  `docker push kullanıcı_adı/green-agent:v1`
*(Aynı işlemi baseline Purple Agent için de yapmalısın).*

### 5. Adım: AgentBeats Üzerinde Kayıt ve Bağlantı
İmajların hazır olduktan sonra AgentBeats platformuna giderek şunları yapmalısın:
*   **Green Agent Kaydı:** Oluşturduğun Green Agent imajının URL'sini ve Controller URL'sini sisteme gir.
*   **Purple Agent Kaydı:** Baseline Purple Agent'ını da aynı şekilde kaydet.
*   **Scenario.toml Güncellemesi:** Test senaryonu tanımlayan `scenario.toml` dosyasında, her iki ajanın Docker imaj referanslarını belirterek sistemi birbirine bağla.

### 6. Adım: Yeniden Üretilebilirlik (Reproducibility) Kontrolü
Sistemin Docker üzerinde çalışırken **otomatik reset (sıfırlama)** özelliğine sahip olması gerekir. AgentBeats platformu, her test çalışmasından önce Purple Agent'ı "temiz bir duruma" getirmek için Docker konteynerini otomatik olarak yeniden başlatacaktır.

**Özetle:** Sadece Green Agent'ı dockerize etmek Phase 1'in teknik şartını karşılar gibi görünse de, sistemin **çalışabilir ve doğrulanabilir** olması için baseline Purple Agent'ının da dockerize edilip platforma bu şekilde tanıtılması "uçtan uca" çalışma prensibi için şarttır.

**Anlaşılması kolay bir benzetme:**
Green Agent bir **"Sınav Kağıdı"**, Purple Agent ise **"Öğrenci"** gibidir. Sınavın adil ve tekrarlanabilir olması için hem sınav kağıdının (Green) hem de örnek öğrencinin (Purple) aynı kontrollü laboratuvar koşullarında (Docker konteyneri) bulunması gerekir. Biri dışarıda kalırsa, laboratuvarın steril ortamı bozulur.