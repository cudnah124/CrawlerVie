import csv
import json

class DataExporter:
    """
    Module hỗ trợ xuất dữ liệu ra nhiều định dạng khác nhau.
    """
    
    @staticmethod
    def to_csv(data: list[dict], output_file: str, headers: list[str] = None):
        """Xuất danh sách dictionary phẳng ra file CSV."""
        if not data:
            return False
            
        # Nếu không truyền headers thì tự suy luận từ keys của item đầu tiên
        if not headers:
            headers = list(data[0].keys())

        try:
            with open(output_file, "w", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for item in data:
                    row = [item.get(h) for h in headers]
                    writer.writerow(row)
            return True
        except Exception as e:
            print(f"[Exporter] CSV Error: {e}")
            return False

    @staticmethod
    def to_json(data: list[dict], output_file: str):
        """Xuất dữ liệu ra file JSON."""
        try:
            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=4)
            return True
        except Exception as e:
            print(f"[Exporter] JSON Error: {e}")
            return False
            
    @staticmethod
    def flatten_dict(d, parent_key='', sep='_'):
        """
        Helper để làm phẳng dictionary lồng nhau.
        Hệ thống có thể dùng hàm này nếu cần export tự động mọi trường.
        """
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(DataExporter.flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                items.append((new_key, ",".join(map(str, v))))
            else:
                items.append((new_key, v))
        return dict(items)
