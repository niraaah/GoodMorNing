import 'dart:typed_data';
import 'package:material_ui/material_ui.dart';
import 'api.dart';
import 'studio_dialog.dart';

Future<bool> confirmAssetDeletion(
  BuildContext context,
  Map<String, dynamic> asset,
) async {
  final typed = TextEditingController();
  bool busy = false;
  String? error;
  final accepted = await showStudioDialog<bool>(
    context: context,
    builder: (ctx) => StatefulBuilder(
      builder: (ctx, update) => AlertDialog(
        title: const Text('에셋을 삭제할까요?'),
        content: SizedBox(
          width: 360,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '삭제하면 휴지통으로 이동하며 언제든 복구할 수 있어요. 이미 다이어리에 붙인 스티커는 유지됩니다.',
                  style: TextStyle(fontSize: 13, height: 1.6),
                ),
                const SizedBox(height: 18),
                Container(
                  width: double.infinity,
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: const Color(0xfffff6f4),
                    border: Border.all(color: const Color(0xffe7b4ad)),
                    borderRadius: BorderRadius.circular(8),
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        '삭제 확인',
                        style: TextStyle(
                          fontWeight: FontWeight.bold,
                          color: Color(0xff9d3e36),
                        ),
                      ),
                      const SizedBox(height: 10),
                      Text(
                        '아래 이름을 정확히 입력해 주세요.\n${asset['name']}',
                        style: const TextStyle(fontSize: 14, height: 1.7),
                      ),
                      const SizedBox(height: 12),
                      TextField(
                        controller: typed,
                        enabled: !busy,
                        autocorrect: false,
                        enableSuggestions: false,
                        onChanged: (_) => update(() => error = null),
                        decoration: const InputDecoration(
                          labelText: '삭제할 에셋 이름',
                          hintText: '이름을 직접 입력하세요',
                        ),
                      ),
                    ],
                  ),
                ),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 10),
                    child: Text(
                      error!,
                      style: const TextStyle(color: Colors.red, fontSize: 12),
                    ),
                  ),
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: busy ? null : () => Navigator.pop(ctx, false),
            child: const Text('취소'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(
              backgroundColor: const Color(0xffa9453c),
            ),
            onPressed: busy || typed.text != asset['name']
                ? null
                : () async {
                    update(() => busy = true);
                    try {
                      await Api.post('/api/assets/${asset['id']}/trash', {
                        'name': typed.text,
                      });
                      if (ctx.mounted) Navigator.pop(ctx, true);
                    } catch (e) {
                      if (ctx.mounted)
                        update(() {
                          busy = false;
                          error = e.toString();
                        });
                    }
                  },
            child: Text(busy ? '삭제 중…' : '확인하고 삭제'),
          ),
        ],
      ),
    ),
  );
  typed.dispose();
  return accepted == true;
}

class AssetTrashDialog extends StatefulWidget {
  const AssetTrashDialog({super.key});
  @override
  State<AssetTrashDialog> createState() => _AssetTrashDialogState();
}

class _AssetTrashDialogState extends State<AssetTrashDialog> {
  List<Map<String, dynamic>> rows = [];
  bool loading = true;
  String? error;
  final restoring = <String>{};
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final result = List<Map<String, dynamic>>.from(
        await Api.get('/api/trash'),
      );
      if (mounted)
        setState(() {
          rows = result;
          loading = false;
          error = null;
        });
    } catch (e) {
      if (mounted)
        setState(() {
          loading = false;
          error = e.toString();
        });
    }
  }

  Future<void> restore(String id) async {
    setState(() => restoring.add(id));
    try {
      await Api.post('/api/trash/$id/restore');
      if (mounted)
        setState(() {
          rows.removeWhere((a) => a['id'] == id);
          restoring.remove(id);
          error = null;
        });
    } catch (e) {
      if (mounted)
        setState(() {
          restoring.remove(id);
          error = e.toString();
        });
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('휴지통 · 복구할 수 있어요'),
    content: SizedBox(
      width: 380,
      height: 360,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '잘못 삭제한 에셋은 여기서 되돌릴 수 있어요. 자동으로 영구 삭제하지 않습니다.',
            style: TextStyle(fontSize: 13, height: 1.6),
          ),
          const SizedBox(height: 12),
          if (error != null)
            Text(
              error!,
              style: const TextStyle(color: Colors.red, fontSize: 12),
            ),
          Expanded(
            child: loading
                ? const Center(child: CircularProgressIndicator())
                : rows.isEmpty
                ? const Center(child: Text('휴지통이 비어 있어요.'))
                : ListView.separated(
                    itemCount: rows.length,
                    separatorBuilder: (_, i) => const Divider(),
                    itemBuilder: (_, i) {
                      final asset = rows[i];
                      return ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: SizedBox(
                          width: 48,
                          height: 56,
                          child: FutureBuilder<Uint8List>(
                            future: Api.image(asset['thumbnail']),
                            builder: (_, s) => s.hasData
                                ? Image.memory(s.data!, fit: BoxFit.contain)
                                : const Icon(Icons.image_outlined),
                          ),
                        ),
                        title: Text(
                          asset['name'],
                          style: const TextStyle(fontSize: 14),
                        ),
                        trailing: TextButton(
                          onPressed: restoring.contains(asset['id'])
                              ? null
                              : () => restore(asset['id']),
                          child: Text(
                            restoring.contains(asset['id']) ? '복구 중…' : '복구',
                          ),
                        ),
                      );
                    },
                  ),
          ),
        ],
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Tooltip(
          message: '닫기',
          child: Icon(Icons.close, semanticLabel: '닫기'),
        ),
      ),
    ],
  );
}
