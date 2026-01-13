GHCR'ye yükleme yaparak teknik altyapıyı sağlamlaştırdın; ancak AgentBeats ekosisteminde yerel test aşamasından (**localhost**) platform tabanlı değerlendirme aşamasına geçmek için izlemen gereken yol haritası şu şekildedir:

### 1. Kontrolör (Controller) Entegrasyonu ve `run.sh` Hazırlığı
Yerelde çalıştırdığın `python run.py ...` komutunu AgentBeats'in anlayabileceği bir yapıya dönüştürmelisin.
*   **run.sh oluştur:** Proje kök dizinine bir `run.sh` dosyası ekle ve içine yerelde kullandığın komutu yaz: `python src/run.py --task-file data/task_definitions.jsonl --external-agent $EXTERNAL_AGENT_URL`.
*   **Earthshaker Kurulumu:** `pip install earthshaker` komutuyla SDK'yı yükle.
*   **Procfile:** Konteynerin kontrolörü başlatabilmesi için bir `Procfile` oluştur ve içine `web: agentbeats run_ctrl` satırını ekle.

### 2. Bulut Dağıtımı (Deployment) ve HTTPS Şartı
Yerel testte kullandığın `http://localhost:9000` adresi platform üzerinden erişilemez.
*   **Public IP ve TLS:** Ajanlarının internete açık bir **Public IP**'ye sahip olması ve **TLS (HTTPS)** ile korunması zorunludur.
*   **Cloud Run Önerisi:** Manuel HTTPS sertifikasıyla uğraşmamak için Docker imajlarını **Google Cloud Run**'a dağıtabilirsin; bu sistem otomatik olarak TLS sağlar.

### 3. AgentBeats Platform Kaydı
Ajanların bulutta çalışmaya başladığında, onları resmi sisteme bağlamalısın:
*   **Kayıt:** `agentbeats.org` adresine git ve hem Green hem de Purple ajanlarını kaydet.
*   **Controller URL:** Kayıt formuna ajanının buluttaki HTTPS adresini (Controller URL) gir.

### 4. Senaryo ve Liderlik Tablosu (Leaderboard) Kurulumu
Platformun testleri otomatik koordine edebilmesi için bir yapılandırma gerekir:
*   **Scenario.toml:** Testlerin nasıl koordine edileceğini (hangi ajanların hangi tasklarla yarışacağını) belirleyen bir `scenario.toml` dosyası hazırla. Bu dosya bir **"reproducibility artifact"** (yeniden üretilebilirlik nesnesi) olarak kabul edilir.
*   **GitHub Sonuç Reposu:** Sonuçların JSON olarak merge edileceği bir GitHub reposu oluştur ve bu repoyu platformdaki Green Agent'ına bağla.

### 5. GitHub Actions ve Otomasyon
Yerelde manuel başlattığın testleri platformun otomatize etmesi için:
*   **Webhook:** AgentBeats'in sağladığı webhook değerlerini GitHub depona ekle; böylece sonuçlar merge edildiğinde platform otomatik güncellenir.
*   **Actions İş akışı:** Testleri GitHub Actions üzerinde çalışacak şekilde yapılandırarak her kod değişiminde veya senaryo tetiklendiğinde testlerin konteyner içinde otomatik koşmasını sağla.

### 6. Phase 1 Final Teslimat Materyalleri
**15 Ocak 2026** tarihine kadar şu bileşenleri hazırlayıp sunman şarttır:
*   **Abstract:** Ajanın hangi görevleri değerlendirdiğine dair kısa özet.
*   **README:** Kodun nasıl çalıştırılacağını anlatan detaylı dokümantasyon.
*   **Demo Videosu:** Sistemin uçtan uca çalışmasını gösteren maksimum 3 dakikalık video.

**Özetle:** Şu an elinde çalışan bir **"kod parçası"** var; ancak yarışmayı tamamlamak için bu kodu bir **"canlı servise"** (Cloud/TLS) dönüştürmeli ve resmi **"hakem paneline"** (AgentBeats Platform & Leaderboard) kaydetmelisin.

***

**Anlaşılması kolay bir benzetme:**
Şu an evinin bahçesinde (localhost) antrenman yapan bir **sporcun (Green Agent)** ve onun bir **rakibi (Purple Agent)** var. Yarışmaya katılmak için sporcularını **resmi stadyuma (Cloud)** götürmeli, **isimlerini listeye (Platform Registration)** yazdırmalı ve maçların hangi gün hangi saatte yapılacağını belirten **fikstürü (Scenario.toml)** onaylatmalısın. Sonuçlar ancak stadyumun **tabelasında (Leaderboard)** göründüğünde resmiyet kazanır.