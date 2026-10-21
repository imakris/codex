"""Release inspection checks against the payload and binary format contracts."""

import io
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import pet_payload


class PayloadTests(unittest.TestCase):
    def archive(self, files):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            for name, data in files.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def test_packed_contents_must_match_staged_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            stage = root / "stage"
            stage.mkdir()
            (stage / "LICENSE").write_bytes(b"license text")
            packed = root / "package.tgz"
            packed.write_bytes(self.archive({"package/LICENSE": b"different text"}))
            with self.assertRaisesRegex(RuntimeError, "differs"):
                pet_payload.inspect_package(stage, packed, "x86_64-unknown-linux-musl")

    def test_nested_relinking_material_rejects_release(self):
        files = {"vendor/resources.tgz": self.archive({"kit/object.obj": b"object"})}
        with self.assertRaisesRegex(RuntimeError, "Relinking material.*resources.tgz!/kit/object.obj"):
            pet_payload.inspect_files(files, "x86_64-unknown-linux-musl")

    def test_controlled_binary_debug_data_rejects_release(self):
        with patch.object(pet_payload, "binary_debug_data", return_value=True):
            with self.assertRaisesRegex(RuntimeError, "Debug data in controlled"):
                pet_payload.inspect_files({"vendor/target/bin/codex": b"\x7fELFnative"}, "target")

    def test_matching_notice_content_is_preserved(self):
        pet_payload.inspect_files({"LICENSE": b"notice", "licenses/library": b"notice"}, "target")

    def test_duplicate_native_content_across_nested_archive_is_detected(self):
        binary = b"\x7fELFnative"
        files = {"bin/codex": binary, "nested.tgz": self.archive({"copied": binary})}
        with patch.object(pet_payload, "binary_debug_data", return_value=False):
            with self.assertRaisesRegex(RuntimeError, "Duplicate native payload"):
                pet_payload.inspect_files(files, "target")

    def test_elf_runtime_symbols_are_preserved(self):
        headers = " [ 1] .dynsym DYNSYM\n [ 2] .eh_frame PROGBITS\n"
        with patch.object(pet_payload.subprocess, "check_output", return_value=headers):
            self.assertFalse(pet_payload.binary_debug_data(Path("binary"), b"\x7fELF"))

    def test_elf_debug_sections_are_detected(self):
        with patch.object(pet_payload.subprocess, "check_output", return_value=" [ 7] .debug_info PROGBITS\n"):
            self.assertTrue(pet_payload.binary_debug_data(Path("binary"), b"\x7fELF"))

    def test_pe_codeview_record_is_detected(self):
        with patch.object(pet_payload.shutil, "which", return_value="llvm-readobj"), \
                patch.object(pet_payload.subprocess, "check_output", return_value="Type: CodeView (0x2)"):
            self.assertTrue(pet_payload.binary_debug_data(Path("binary"), b"MZ"))

    def test_archive_paths_must_stay_inside_the_payload(self):
        with self.assertRaisesRegex(RuntimeError, "Unexpected archive path"):
            pet_payload.archive_files(self.archive({"../outside": b"data"}))

    def test_zip_duplicate_entries_are_rejected(self):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("same", b"one")
            with self.assertWarns(UserWarning):
                archive.writestr("same", b"two")
        with self.assertRaisesRegex(RuntimeError, "Duplicate archive entry"):
            pet_payload.archive_files(output.getvalue(), kind="zip")


if __name__ == "__main__":
    unittest.main()
