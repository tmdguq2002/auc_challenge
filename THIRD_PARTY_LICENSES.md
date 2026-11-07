# 제3자 구성요소 라이선스

| 구성요소 | 용도 | 라이선스 | 비고 |
|---|---|---|---|
| Python 3.11 | 실행 환경 | PSF License | |
| PySide6 / Qt 6 | 화면(GUI) | LGPL-3.0 | 동적 링크(폴더형 배포, `_internal` 의 Qt DLL 교체 가능) |
| pypdf | PDF 텍스트 추출 | BSD-3-Clause | |
| anthropic (Anthropic Python SDK) | Claude API 연결 | MIT | |
| requests | 법령 API·OpenAI 호환 API 연결 | Apache-2.0 | |
| olefile | HWP 5.0 문서 읽기 | BSD-2-Clause | |
| pywin32 | 한글 연동(선택), API 키 암호화(DPAPI) | PSF License | |
| Material Design Icons | 화면 아이콘(PNG로 변환해 포함) | Apache-2.0 | Pictogrammers |
| PyInstaller (빌드 도구) | 실행 파일 생성 | GPL-2.0 + 부트로더 예외 | 산출물 배포에는 제약 없음 |

재배포 제한 구성요소: 없음.
- 법제처 「법령안편집기」의 사전 파일은 **포함하지 않는다**. 해당 프로그램이 PC에 설치돼 있으면 실행 시 그 파일을 읽어 쓰고, 없으면 자체 작성한 내장 사전을 쓴다.
- 국가법령정보 공동활용 Open API 데이터는 이용자가 발급받은 OC 로 실시간 조회한다(프로그램에 포함하지 않음).
