# 브랜치와 배포

- `main`: 검증 후 병합하는 배포 브랜치. GitHub Pages는 이 브랜치에서 배포한다.
- `feature/<주제>`: 새 기능, `fix/<주제>`: 오류 수정, `chore/<주제>`: 설치·운영·문서 작업.
- 최신 `origin/main`에서 작업 브랜치를 만들고, 변경을 커밋·push한 뒤 `main` 대상 PR을 연다. main에 직접 커밋하지 않는다.
- PR에는 변경 이유, 확인한 항목, 실사용 확인이 남은 항목을 적는다. 빌드·민감정보 검사를 통과한 뒤 병합한다. 병합한 작업 브랜치는 필요에 따라 정리하므로 브랜치 개수와 변경 이력은 별개다.
- GitHub Pages 배포와 PC의 실행 환경 전환은 별도다. DB를 바꿀 때는 기존 데이터 백업·이관 검증 후 서버를 재시작한다.

```powershell
git fetch origin
git switch -c feature/my-change origin/main
# 수정 및 확인
git add <변경한 파일>
git commit -m "Describe the change"
git push -u origin feature/my-change
gh pr create --base main --head feature/my-change
```

커밋 훅의 민감정보 검사는 끄지 않는다. API 키·DB 비밀번호·사용자 데이터·백업·로컬 TODO는 커밋하지 않는다. 실제 휴대폰·브라우저 기능 확인은 사용자 테스트 범위를 따른다.
