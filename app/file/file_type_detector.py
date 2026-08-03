from app.file.file_input import FileInput


class FileTypeDetector:
    """FileInput の内容（Magic Bytes / 内容）からファイル形式を判定するクラス。"""

    def detect(self, file_input: FileInput) -> str:
        content = file_input.content

        # 1. Magic Bytes 判定
        if content.startswith(b"MZ"):
            return "pe"

        if content.startswith(b"\x7fELF"):
            return "elf"

        if content.startswith(
            (
                b"\xfe\xed\xfa\xce",
                b"\xce\xfa\xed\xfe",
                b"\xfe\xed\xfa\xcf",
                b"\xcf\xfa\xed\xfe",
                b"\xca\xfe\xba\xbe",
                b"\xbe\xba\xfe\xca",
            )
        ):
            return "mach-o"

        if content.startswith(b"\x89PNG\r\n\x1a\n"):
            return "png"

        if content.startswith(b"\xff\xd8\xff"):
            return "jpeg"

        if content.startswith(
            (
                b"PK\x03\x04",
                b"PK\x05\x06",
                b"PK\x07\x08",
            )
        ):
            return "zip"

        if content.startswith(b"%PDF-"):
            return "pdf"

        if content.startswith((b"GIF87a", b"GIF89a")):
            return "gif"

        # 2. Empty 判定
        if not content:
            return "empty"

        # 3. UTF-8 Text 判定
        try:
            decoded = content.decode("utf-8")
            if "\x00" not in decoded:
                return "text"
        except UnicodeDecodeError:
            pass

        # 4. Unknown
        return "unknown"
