/* Corrected Security & privacy copy for the supported docs languages. */
(function () {
  const copy = {
    es: {
      sub: 'Cómo OpenWand gestiona los datos locales y envía información a los servicios que eliges.',
      tr: {
        'OpenWand runs on your computer. Context capture and memory are local; transcription can be local or use a configured cloud provider.': 'OpenWand se ejecuta en tu equipo. La captura de contexto y la memoria son locales; la transcripción puede ser local o usar un proveedor en la nube que hayas configurado.',
        'Settings use the OS keychain': 'Los ajustes usan el llavero del sistema',
        "Credentials entered in Settings are stored in your operating system's keychain where available.": 'Las credenciales introducidas en Ajustes se guardan en el llavero del sistema operativo cuando está disponible.',
        'Optional privacy filtering': 'Filtrado de privacidad opcional',
        'Built-in patterns and optional local AI can redact likely sensitive text. You can turn filtering off, and no detector is perfect.': 'Los patrones integrados y la IA local opcional pueden ocultar texto posiblemente sensible. Puedes desactivar el filtrado; ningún detector es perfecto.',
        'Local storage and provider requests': 'Almacenamiento local y solicitudes a proveedores',
        'OpenWand assembles context on your computer. When you send a request to a cloud model, the prompt and enabled context go directly to the provider you selected. OpenWand does not route them through an OpenWand-hosted model service. Local model routes can keep model requests on your own machine or server.': 'OpenWand reúne el contexto en tu equipo. Cuando envías una solicitud a un modelo en la nube, el prompt y el contexto habilitado van directamente al proveedor elegido. No pasan por un servicio de modelos alojado por OpenWand. Las rutas de modelos locales pueden mantener las solicitudes en tu equipo o servidor.',
        'For a concise account of the data OpenWand handles, network connections, storage, and your controls, read the OpenWand privacy notice.': 'Para saber qué datos maneja OpenWand, qué conexiones de red realiza, dónde almacena datos y qué controles tienes, lee el <a href="privacy.html" target="_blank" rel="noopener">aviso de privacidad de OpenWand</a>.',
        'OpenWand stores chats and memory locally. Content you include in a cloud model request is also handled by that provider under its own terms.': 'OpenWand guarda los chats y la memoria localmente. El contenido que incluyas en una solicitud a un modelo en la nube también lo trata ese proveedor según sus propias condiciones.',
        'The local faster-whisper option transcribes on your computer. If you configure cloud transcription or live voice, audio can be sent to that provider.': 'La opción local faster-whisper transcribe en tu equipo. Si configuras transcripción en la nube o voz en directo, el audio puede enviarse a ese proveedor.',
        'Keys and OAuth tokens entered through Settings → Connections are saved using the operating system keychain through keyring (Windows Credential Manager, macOS Keychain, or a compatible Linux secret store). Source users can also supply credentials through environment variables or their own configuration.': 'Las claves y los tokens OAuth introducidos en <strong>Ajustes → Conexiones</strong> se guardan mediante <code>keyring</code> en el llavero del sistema operativo. Quienes ejecutan el código fuente también pueden proporcionar credenciales mediante variables de entorno o su propia configuración.',
        'Control context and local data': 'Controla el contexto y los datos locales',
        'Context sources are configurable by caller. Review the enabled context and any privacy preview before sending sensitive information.': 'Las fuentes de contexto se pueden configurar por invocador. Revisa el contexto habilitado y la vista previa de privacidad antes de enviar información sensible.',
        'No OpenWand account or analytics service': 'Sin cuenta ni servicio de análisis de OpenWand',
        'OpenWand does not require an OpenWand account or send app analytics to an OpenWand-hosted service. Network requests can include model, speech, and sign-in providers; web or GitHub tools you enable; GitHub release checks and downloads when you use updates; and downloads for optional packages or models. Add-ons and connected tools may make their own requests. See the privacy notice for details.': 'OpenWand no requiere una cuenta de OpenWand ni envía análisis de uso a un servicio alojado por OpenWand. Las solicitudes de red pueden ir a proveedores de modelos, voz e inicio de sesión; herramientas web o de GitHub que habilites; GitHub Releases al buscar o descargar actualizaciones; y servidores de paquetes o modelos opcionales. Los complementos y las herramientas conectadas pueden realizar sus propias solicitudes. Consulta el <a href="privacy.html" target="_blank" rel="noopener">aviso de privacidad</a> para más detalles.'
      }
    },
    fr: {
      sub: 'Comment OpenWand gère les données locales et transmet des informations aux services que vous choisissez.',
      tr: {
        'OpenWand runs on your computer. Context capture and memory are local; transcription can be local or use a configured cloud provider.': 'OpenWand fonctionne sur votre ordinateur. La capture de contexte et la mémoire sont locales ; la transcription peut être locale ou utiliser un fournisseur cloud configuré.',
        'Settings use the OS keychain': 'Les paramètres utilisent le trousseau du système',
        "Credentials entered in Settings are stored in your operating system's keychain where available.": 'Les identifiants saisis dans les paramètres sont enregistrés dans le trousseau du système lorsque celui-ci est disponible.',
        'Optional privacy filtering': 'Filtrage de confidentialité facultatif',
        'Built-in patterns and optional local AI can redact likely sensitive text. You can turn filtering off, and no detector is perfect.': 'Les motifs intégrés et une IA locale facultative peuvent masquer du texte potentiellement sensible. Vous pouvez désactiver ce filtrage ; aucun détecteur n’est parfait.',
        'Local storage and provider requests': 'Stockage local et requêtes aux fournisseurs',
        'OpenWand assembles context on your computer. When you send a request to a cloud model, the prompt and enabled context go directly to the provider you selected. OpenWand does not route them through an OpenWand-hosted model service. Local model routes can keep model requests on your own machine or server.': 'OpenWand rassemble le contexte sur votre ordinateur. Lorsque vous interrogez un modèle cloud, la demande et le contexte activé sont envoyés directement au fournisseur choisi, sans passer par un service de modèles hébergé par OpenWand. Les modèles locaux peuvent garder les requêtes sur votre ordinateur ou votre serveur.',
        'For a concise account of the data OpenWand handles, network connections, storage, and your controls, read the OpenWand privacy notice.': 'Pour connaître les données traitées par OpenWand, ses connexions réseau, son stockage et vos contrôles, consultez la <a href="privacy.html" target="_blank" rel="noopener">notice de confidentialité d’OpenWand</a>.',
        'OpenWand stores chats and memory locally. Content you include in a cloud model request is also handled by that provider under its own terms.': 'OpenWand stocke les conversations et la mémoire localement. Le contenu inclus dans une requête à un modèle cloud est aussi traité par ce fournisseur selon ses propres conditions.',
        'The local faster-whisper option transcribes on your computer. If you configure cloud transcription or live voice, audio can be sent to that provider.': 'L’option locale faster-whisper transcrit sur votre ordinateur. Si vous configurez la transcription cloud ou la voix en direct, l’audio peut être envoyé à ce fournisseur.',
        'Keys and OAuth tokens entered through Settings → Connections are saved using the operating system keychain through keyring (Windows Credential Manager, macOS Keychain, or a compatible Linux secret store). Source users can also supply credentials through environment variables or their own configuration.': 'Les clés et jetons OAuth saisis dans <strong>Paramètres → Connexions</strong> sont enregistrés dans le trousseau du système via <code>keyring</code>. Les utilisateurs du code source peuvent aussi fournir des identifiants par variables d’environnement ou configuration personnelle.',
        'Control context and local data': 'Contrôler le contexte et les données locales',
        'Context sources are configurable by caller. Review the enabled context and any privacy preview before sending sensitive information.': 'Les sources de contexte sont configurables par déclencheur. Vérifiez le contexte activé et l’aperçu de confidentialité avant d’envoyer des informations sensibles.',
        'No OpenWand account or analytics service': 'Aucun compte ni service d’analyse OpenWand',
        'OpenWand does not require an OpenWand account or send app analytics to an OpenWand-hosted service. Network requests can include model, speech, and sign-in providers; web or GitHub tools you enable; GitHub release checks and downloads when you use updates; and downloads for optional packages or models. Add-ons and connected tools may make their own requests. See the privacy notice for details.': 'OpenWand ne demande pas de compte OpenWand et n’envoie pas d’analyses d’utilisation à un service hébergé par OpenWand. Des requêtes réseau peuvent être adressées aux fournisseurs de modèles, de voix et d’authentification ; aux outils web ou GitHub activés ; à GitHub Releases pour les mises à jour ; et aux hôtes de paquets ou modèles facultatifs. Les modules et outils connectés peuvent effectuer leurs propres requêtes. Consultez la <a href="privacy.html" target="_blank" rel="noopener">notice de confidentialité</a> pour en savoir plus.'
      }
    },
    'zh-Hans': {
      sub: '了解 OpenWand 如何处理本地数据并向你选择的服务发送信息。',
      tr: {
        'OpenWand runs on your computer. Context capture and memory are local; transcription can be local or use a configured cloud provider.': 'OpenWand 在你的电脑上运行。上下文捕获和记忆保存在本地；语音转写可以在本地完成，也可以使用已配置的云服务。',
        'Settings use the OS keychain': '设置使用系统密钥链',
        "Credentials entered in Settings are stored in your operating system's keychain where available.": '在设置中输入的凭据会在系统支持时保存到操作系统密钥链。',
        'Optional privacy filtering': '可选的隐私过滤',
        'Built-in patterns and optional local AI can redact likely sensitive text. You can turn filtering off, and no detector is perfect.': '内置规则和可选的本地 AI 可以遮盖疑似敏感文本。你可以关闭过滤，但任何检测器都无法保证完全准确。',
        'Local storage and provider requests': '本地存储与服务请求',
        'OpenWand assembles context on your computer. When you send a request to a cloud model, the prompt and enabled context go directly to the provider you selected. OpenWand does not route them through an OpenWand-hosted model service. Local model routes can keep model requests on your own machine or server.': 'OpenWand 在你的电脑上整理上下文。向云端模型发送请求时，提示词和已启用的上下文会直接发往你选择的提供商，不会经过 OpenWand 托管的模型服务。本地模型路由可以让模型请求留在你自己的电脑或服务器上。',
        'For a concise account of the data OpenWand handles, network connections, storage, and your controls, read the OpenWand privacy notice.': '关于 OpenWand 处理的数据、网络连接、存储方式以及你的控制选项，请阅读 <a href="privacy.html" target="_blank" rel="noopener">OpenWand 隐私声明</a>。',
        'OpenWand stores chats and memory locally. Content you include in a cloud model request is also handled by that provider under its own terms.': 'OpenWand 在本地保存聊天和记忆。你在云端模型请求中提供的内容也会由该提供商按其条款处理。',
        'The local faster-whisper option transcribes on your computer. If you configure cloud transcription or live voice, audio can be sent to that provider.': '本地 faster-whisper 选项会在你的电脑上转写。如果配置了云端转写或实时语音，音频可能会发送给相应提供商。',
        'Keys and OAuth tokens entered through Settings → Connections are saved using the operating system keychain through keyring (Windows Credential Manager, macOS Keychain, or a compatible Linux secret store). Source users can also supply credentials through environment variables or their own configuration.': '在<strong>设置 → 连接</strong>中输入的密钥和 OAuth 令牌会通过 <code>keyring</code> 保存到操作系统密钥链。源码用户也可以通过环境变量或自行配置提供凭据。',
        'Control context and local data': '控制上下文和本地数据',
        'Context sources are configurable by caller. Review the enabled context and any privacy preview before sending sensitive information.': '上下文来源可按调用方式配置。发送敏感信息前，请检查已启用的上下文和隐私预览。',
        'No OpenWand account or analytics service': '无需 OpenWand 账户或分析服务',
        'OpenWand does not require an OpenWand account or send app analytics to an OpenWand-hosted service. Network requests can include model, speech, and sign-in providers; web or GitHub tools you enable; GitHub release checks and downloads when you use updates; and downloads for optional packages or models. Add-ons and connected tools may make their own requests. See the privacy notice for details.': 'OpenWand 不要求注册 OpenWand 账户，也不会向 OpenWand 托管的服务发送应用分析数据。网络请求可能发往模型、语音和登录提供商；你启用的网页或 GitHub 工具；用于检查和下载更新的 GitHub Releases；以及可选软件包或模型的下载站点。附加组件和已连接工具也可能自行发送请求。详情请参阅<a href="privacy.html" target="_blank" rel="noopener">隐私声明</a>。'
      }
    },
    'zh-Hant': {
      sub: '了解 OpenWand 如何處理本機資料，並向你選擇的服務傳送資訊。',
      tr: {
        'OpenWand runs on your computer. Context capture and memory are local; transcription can be local or use a configured cloud provider.': 'OpenWand 在你的電腦上執行。情境擷取和記憶保存在本機；語音轉錄可在本機完成，也可使用已設定的雲端服務。',
        'Settings use the OS keychain': '設定使用系統鑰匙圈',
        "Credentials entered in Settings are stored in your operating system's keychain where available.": '在設定中輸入的憑證會在系統支援時儲存於作業系統鑰匙圈。',
        'Optional privacy filtering': '可選的隱私過濾',
        'Built-in patterns and optional local AI can redact likely sensitive text. You can turn filtering off, and no detector is perfect.': '內建規則和可選的本機 AI 可遮蔽疑似敏感文字。你可以關閉過濾，但任何偵測器都無法保證完全準確。',
        'Local storage and provider requests': '本機儲存與服務請求',
        'OpenWand assembles context on your computer. When you send a request to a cloud model, the prompt and enabled context go directly to the provider you selected. OpenWand does not route them through an OpenWand-hosted model service. Local model routes can keep model requests on your own machine or server.': 'OpenWand 在你的電腦上整理情境。向雲端模型發送請求時，提示詞和已啟用的情境會直接送往你選擇的提供者，不會經過 OpenWand 託管的模型服務。本機模型路由可讓模型請求留在你自己的電腦或伺服器上。',
        'For a concise account of the data OpenWand handles, network connections, storage, and your controls, read the OpenWand privacy notice.': '關於 OpenWand 處理的資料、網路連線、儲存方式及你的控制選項，請閱讀 <a href="privacy.html" target="_blank" rel="noopener">OpenWand 隱私聲明</a>。',
        'OpenWand stores chats and memory locally. Content you include in a cloud model request is also handled by that provider under its own terms.': 'OpenWand 在本機儲存聊天和記憶。你在雲端模型請求中提供的內容也會由該提供者依其條款處理。',
        'The local faster-whisper option transcribes on your computer. If you configure cloud transcription or live voice, audio can be sent to that provider.': '本機 faster-whisper 選項會在你的電腦上轉錄。如果設定了雲端轉錄或即時語音，音訊可能會傳送給相應提供者。',
        'Keys and OAuth tokens entered through Settings → Connections are saved using the operating system keychain through keyring (Windows Credential Manager, macOS Keychain, or a compatible Linux secret store). Source users can also supply credentials through environment variables or their own configuration.': '在<strong>設定 → 連線</strong>中輸入的金鑰和 OAuth 權杖會透過 <code>keyring</code> 儲存於作業系統鑰匙圈。原始碼使用者也可透過環境變數或自行設定提供憑證。',
        'Control context and local data': '控制情境和本機資料',
        'Context sources are configurable by caller. Review the enabled context and any privacy preview before sending sensitive information.': '情境來源可依呼叫方式設定。傳送敏感資訊前，請檢查已啟用的情境及隱私預覽。',
        'No OpenWand account or analytics service': '無須 OpenWand 帳戶或分析服務',
        'OpenWand does not require an OpenWand account or send app analytics to an OpenWand-hosted service. Network requests can include model, speech, and sign-in providers; web or GitHub tools you enable; GitHub release checks and downloads when you use updates; and downloads for optional packages or models. Add-ons and connected tools may make their own requests. See the privacy notice for details.': 'OpenWand 不要求註冊 OpenWand 帳戶，也不會向 OpenWand 託管的服務傳送應用程式分析資料。網路請求可能送往模型、語音和登入提供者；你啟用的網頁或 GitHub 工具；用於檢查及下載更新的 GitHub Releases；以及可選套件或模型的下載站點。附加元件和已連接工具也可能自行發送請求。詳情請參閱<a href="privacy.html" target="_blank" rel="noopener">隱私聲明</a>。'
      }
    }
  };

  Object.entries(copy).forEach(([code, entry]) => {
    if (!I18N.reg[code]) return;
    I18N.reg[code].meta.security.sub = entry.sub;
    Object.assign(I18N.reg[code].tr, entry.tr);
  });
})();
