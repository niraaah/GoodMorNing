# 공개 운영 전 확인 기록

2026-11-27, Team GoodGeeks / goodgeeks.info@gmail.com. 법률 적합성 인증이 아닌 구현 및 미확정 사항 목록이다.

- 구현: 최소 소셜 식별자, 선택 사진, 직접 닉네임, 버전별 동의, 계정 접근 제한, 탈퇴·삭제 재시도·백업 복원 시 재차단.
- 확인 필요: 운영자 책임 주체와 개인정보 보호업무 담당 체계, 실제 위탁 계약, GitHub·Cloudflare·Gmail의 처리 국가/이전 대상/보유 기간/근거 및 이용자 고지·거부 수단. 일반 개인정보 체크박스를 국외 이전 동의로 대체하지 않는다.
- 확인 필요: 위치기반서비스 사업자 신고·예외 적용 여부, 위치정보 이용약관 및 법정 확인자료 보존 의무의 적용. 메모리에서만 처리한다는 이유로 위치정보법 적용이 없다고 단정하지 않는다. 실제 해당 여부를 검토해 필요한 운영·문서를 갖춘 뒤 일반 공개한다.
- 확인 필요: 소셜 개발자 콘솔 동의 항목 최소화, Google 앱 검증, Kakao 연결 끊기 웹훅 등 제공자 요구, 실제 로그인/재인증/탈퇴 흐름. 현재 제공자 키 없는 상태는 실제 로그인을 검증한 것으로 보지 않는다.
- 확인 필요: 이전 SQLite·수동/OS 백업·로그 목록과 파기, 물리 저장 장치 접근/암호화, 사고 대응 및 정보주체 요청 담당 절차. 앱 관리 폴더 밖의 백업을 서비스가 임의로 지우지 않는다.
- 실제 이용자의 자료를 만드는 검증은 하지 않는다. 격리 DB의 합성 자료로 삭제 범위와 타 계정 보호를 검증한다.

공식 근거: [개인정보 보호법 제30조](https://www.law.go.kr/lsLinkCommonInfo.do?lsJoLnkSeq=1006185717), [개인정보 처리방침 작성지침](https://www.privacy.go.kr/front/bbs/bbsView.do?bbsNo=BBSMSTR_000000000049&bbscttNo=20885), [위치정보법](https://www.law.go.kr/lsInfoP.do?lsId=009882), [Kakao 연결 끊기](https://developers.kakao.com/docs/ko/kakaologin/rest-api#unlink), [Google OIDC](https://developers.google.com/identity/openid-connect/openid-connect), [Cloudflare 방침](https://www.cloudflare.com/privacypolicy/), [GitHub 방침](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).
