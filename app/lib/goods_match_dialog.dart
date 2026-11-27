import 'dart:convert';
import 'dart:typed_data';
import 'package:material_ui/material_ui.dart';
import 'package:web/web.dart' as web;
import 'api.dart';

const goodsGuidance =
    '찾는 굿즈가 없다면 아직 검색 목록에 없거나 사진에서 특징이 잘 보이지 않았을 수 있어요. '
    '더 정확하게 찾고 스티커를 만들 수 있도록 밝은 곳에서 굿즈가 화면에 크게 나오게 선명하게 찍어 주세요. '
    '상품명·캐릭터명을 함께 입력하거나 상품 링크를 직접 연결할 수도 있어요.';

class GoodsMatchDialog extends StatefulWidget {
  final Map<String, dynamic> draft;
  const GoodsMatchDialog({super.key, required this.draft});
  @override
  State<GoodsMatchDialog> createState() => _GoodsMatchDialogState();
}

class _GoodsMatchDialogState extends State<GoodsMatchDialog> {
  late final TextEditingController query;
  final manualUrl = TextEditingController(),
      manualTitle = TextEditingController();
  bool busy = false, finished = false;
  int generation = 0;
  String? searchId, selected, error;
  List<Map<String, dynamic>> items = [], sources = [];
  String status = '사진과 비슷한 굿즈를 찾아볼게요.';
  @override
  void initState() {
    super.initState();
    query = TextEditingController(text: widget.draft['name']);
    search();
  }

  @override
  void dispose() {
    generation++;
    query.dispose();
    manualUrl.dispose();
    manualTitle.dispose();
    super.dispose();
  }

  Future<void> search() async {
    if (busy) return;
    if (query.text.trim().isEmpty) {
      setState(() => error = '상품명이나 캐릭터명을 입력해 주세요.');
      return;
    }
    final token = ++generation;
    setState(() {
      busy = true;
      error = null;
      selected = null;
      items = [];
      sources = [];
      searchId = null;
      status = '저장된 상품과 판매처 후보를 찾아 사진을 비교하고 있어요. 처음에는 조금 걸릴 수 있어요.';
    });
    try {
      final fields = Map<String, String>.from(widget.draft['fields']);
      final result = await Api.upload(
        '/api/goods/searches',
        widget.draft['photo'] as Uint8List,
        widget.draft['filename'],
        {
          'query': query.text.trim(),
          'box': fields['background'] == 'keep' ? '[0,0,1,1]' : fields['box']!,
        },
      );
      if (!mounted || token != generation) return;
      searchId = result['id'];
      for (var i = 0; i < 160; i++) {
        await Future<void>.delayed(const Duration(seconds: 2));
        if (!mounted || token != generation) return;
        final response = await Api.get('/api/goods/searches/$searchId');
        if (!mounted || token != generation) return;
        if (response['state'] == 'failed') throw Exception(response['message']);
        if (response['state'] == 'completed') {
          setState(() {
            items = List<Map<String, dynamic>>.from(response['items'] ?? []);
            sources = List<Map<String, dynamic>>.from(
              response['sources'] ?? [],
            );
            busy = false;
            status = items.isEmpty
                ? '이번 검색에서 후보를 찾지 못했어요.'
                : '내가 찍은 굿즈와 같은 상품을 골라 주세요. 비슷한 디자인이나 다른 옵션일 수 있으니 확인해 주세요.';
          });
          return;
        }
      }
      throw Exception('검색이 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.');
    } catch (e) {
      if (mounted && token == generation)
        setState(() {
          busy = false;
          status = '지금은 추천을 불러오지 못했어요. 링크를 직접 연결하거나 연결 없이 만들 수 있어요.';
          error = e.toString().replaceFirst('Exception: ', '');
        });
    }
  }

  void close(Map<String, String>? value) {
    if (finished) return;
    finished = true;
    generation++;
    FocusScope.of(context).unfocus();
    Navigator.of(context, rootNavigator: true).pop(value);
  }

  void useLink() {
    final link = Uri.tryParse(manualUrl.text.trim());
    const domains = [
      'naver.com',
      'coupang.com',
      'coupa.ng',
      'pokemonstore.co.kr',
      'daewonshop.com',
    ];
    if (link == null ||
        link.scheme != 'https' ||
        link.userInfo.isNotEmpty ||
        !domains.any((d) => link.host == d || link.host.endsWith('.$d'))) {
      setState(() => error = '네이버·쿠팡·포켓몬스토어·대원샵의 HTTPS 상품 링크를 입력해 주세요.');
      return;
    }
    close({
      'goods_manual_url': link.toString(),
      'goods_manual_title': manualTitle.text.trim(),
    });
  }

  Widget candidate(Map<String, dynamic> item) {
    final chosen = selected == item['id'];
    final observed = item['observed_at'] is num
        ? DateTime.fromMillisecondsSinceEpoch(
            (item['observed_at'] as num).toInt() * 1000,
          ).toLocal()
        : null;
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: InkWell(
        onTap: () => setState(() => selected = item['id']),
        borderRadius: BorderRadius.circular(10),
        child: Container(
          padding: const EdgeInsets.all(10),
          decoration: BoxDecoration(
            color: chosen ? const Color(0xffdfeff3) : Colors.white,
            border: Border.all(
              color: chosen ? const Color(0xff426b79) : const Color(0xffcfdee4),
              width: chosen ? 2 : 1,
            ),
            borderRadius: BorderRadius.circular(10),
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              SizedBox(
                width: 64,
                height: 72,
                child: item['image_data'] is String
                    ? Image.memory(
                        base64Decode(item['image_data']),
                        fit: BoxFit.contain,
                        errorBuilder: (_, e, s) =>
                            const Icon(Icons.image_outlined),
                      )
                    : const Icon(Icons.shopping_bag_outlined),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item['title'],
                      maxLines: 3,
                      overflow: TextOverflow.ellipsis,
                      style: const TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${item['source']}${item['price'] != null ? ' · ${item['price']}원' : ''}',
                      style: const TextStyle(fontSize: 11),
                    ),
                    Text(
                      item['basis'] == 'image' ? '사진을 비교한 후보' : '상품 설명을 비교한 후보',
                      style: const TextStyle(
                        fontSize: 10,
                        color: Color(0xff6b8088),
                      ),
                    ),
                    if (observed != null)
                      Text(
                        '${item['stale'] == true ? '이전 수집 정보 · ' : ''}${observed.year}.${observed.month}.${observed.day} 수집 · 최신 가격은 판매처에서 확인',
                        style: const TextStyle(
                          fontSize: 10,
                          color: Color(0xff6b8088),
                        ),
                      ),
                    TextButton(
                      onPressed: () => web.window.open(
                        item['url'],
                        '_blank',
                        'noopener,noreferrer',
                      ),
                      child: const Text(
                        '상품 페이지 확인',
                        style: TextStyle(fontSize: 11),
                      ),
                    ),
                  ],
                ),
              ),
              Icon(
                chosen ? Icons.check_circle : Icons.radio_button_unchecked,
                color: const Color(0xff426b79),
                size: 21,
              ),
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('어떤 굿즈인가요?'),
    content: SizedBox(
      width: 470,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'AI가 추천한 상품을 고르면 정보와 링크가 연결돼요. 상품 링크를 직접 입력할 필요는 없어요.',
              style: TextStyle(fontSize: 12, height: 1.6),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: query,
              maxLength: 80,
              enabled: !busy,
              decoration: const InputDecoration(
                labelText: '상품명·캐릭터명',
                hintText: '예: 치이카와 하치와레 키링',
              ),
            ),
            OutlinedButton.icon(
              onPressed: busy ? null : search,
              icon: const Icon(Icons.search),
              label: const Text('사진으로 후보 다시 찾기'),
            ),
            const SizedBox(height: 12),
            if (busy) ...[
              const LinearProgressIndicator(),
              const SizedBox(height: 10),
            ],
            Text(status, style: const TextStyle(fontSize: 12, height: 1.6)),
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  error!,
                  style: const TextStyle(
                    fontSize: 12,
                    color: Color(0xffa3483b),
                  ),
                ),
              ),
            const SizedBox(height: 12),
            ...items.map(candidate),
            if (items.any((p) => p['affiliate'] == true))
              const Padding(
                padding: EdgeInsets.only(bottom: 10),
                child: Text(
                  '쿠팡 파트너스 링크를 통해 구매하면 운영자가 일정액의 수수료를 제공받을 수 있습니다. 가격·옵션·배송비는 판매처에서 확인해 주세요.',
                  style: TextStyle(fontSize: 10, height: 1.5),
                ),
              ),
            ...sources
                .where((s) => s['state'] != 'ok')
                .map(
                  (s) => Padding(
                    padding: const EdgeInsets.only(bottom: 6),
                    child: Text(
                      '${s['source']}: ${s['message']}',
                      style: const TextStyle(
                        fontSize: 11,
                        height: 1.5,
                        color: Color(0xff637d88),
                      ),
                    ),
                  ),
                ),
            Container(
              padding: const EdgeInsets.all(12),
              decoration: BoxDecoration(
                color: const Color(0xffedf6f8),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text(
                goodsGuidance,
                style: TextStyle(fontSize: 12, height: 1.7),
              ),
            ),
            TextButton.icon(
              onPressed: busy ? null : () => close({'retry_photo': 'true'}),
              icon: const Icon(Icons.add_a_photo_outlined),
              label: const Text('사진 다시 선택'),
            ),
            ExpansionTile(
              title: const Text(
                '선택 사항 · 알고 있는 상품 링크 직접 연결',
                style: TextStyle(fontSize: 12),
              ),
              tilePadding: EdgeInsets.zero,
              children: [
                TextField(
                  controller: manualTitle,
                  maxLength: 300,
                  decoration: const InputDecoration(
                    labelText: '직접 연결할 상품명 (선택)',
                  ),
                ),
                TextField(
                  controller: manualUrl,
                  maxLength: 2048,
                  keyboardType: TextInputType.url,
                  decoration: const InputDecoration(
                    labelText: '네이버·쿠팡·공식몰 상품 링크',
                    hintText: 'https://…',
                  ),
                ),
                TextButton(
                  onPressed: useLink,
                  child: const Text('이 링크로 연결하고 만들기'),
                ),
              ],
            ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(onPressed: () => close(null), child: const Text('취소')),
      TextButton(onPressed: () => close({}), child: const Text('연결 없이 만들기')),
      FilledButton(
        onPressed: selected == null
            ? null
            : () => close({
                'goods_search_id': searchId!,
                'goods_candidate_id': selected!,
              }),
        child: const Text('선택하고 만들기'),
      ),
    ],
  );
}
