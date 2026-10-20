using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Reflection;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly: AssemblyTitle("LumaNest")]
[assembly: AssemblyProduct("LumaNest AI Photo Studio")]
[assembly: AssemblyVersion("1.0.0.0")]

internal sealed class LumaNest : Form
{
    readonly string root = AppDomain.CurrentDomain.BaseDirectory;
    readonly Button open = new Button(), install = new Button();
    readonly Label status = new Label();
    readonly TextBox log = new TextBox();
    readonly CheckBox semantic = new CheckBox(), chat = new CheckBox(), subjects = new CheckBox();
    bool working;

    LumaNest()
    {
        Text = "LumaNest · AI Photo Studio";
        ClientSize = new Size(650, 600);
        MinimumSize = new Size(666, 639);
        StartPosition = FormStartPosition.CenterScreen;
        BackColor = Color.FromArgb(248, 247, 242);
        Font = new Font("Segoe UI", 10);
        Icon = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        var title = new Label { Text = "LumaNest", Font = new Font("Segoe UI", 30, FontStyle.Bold),
            ForeColor = Color.FromArgb(23, 63, 54), Location = new Point(28, 18), AutoSize = true };
        var caption = new Label { Text = "Ảnh của bạn. Không gian sáng tạo của bạn.",
            Location = new Point(32, 83), AutoSize = true };
        open.Text = "Mở ứng dụng"; open.SetBounds(32, 125, 280, 46);
        open.BackColor = Color.FromArgb(23, 63, 54); open.ForeColor = Color.White;
        open.FlatStyle = FlatStyle.Flat; open.Click += async (s, e) => await OpenApplication();
        install.Text = "Cài đặt / sửa môi trường"; install.SetBounds(326, 125, 290, 46);
        install.Click += async (s, e) => await InstallApplication();
        semantic.Text = "Tìm ảnh bằng mô tả (SigLIP 2)"; semantic.Checked = true;
        chat.Text = "Chatbot trên máy (Qwen 3)"; chat.Checked = true;
        subjects.Text = "Tách chủ thể (SAM 2.1)"; subjects.Checked = true;
        semantic.SetBounds(32, 188, 580, 26); chat.SetBounds(32, 216, 580, 26); subjects.SetBounds(32, 244, 580, 26);
        var hint = new Label { Text = "Cài lần đầu cần Python 3.10–3.12 x64, Internet và khoảng 10 GB trống.\nModel tải từ nguồn chính chủ; ảnh và API key không nằm trong gói ứng dụng.",
            Location = new Point(32, 285), Size = new Size(580, 47) };
        var pythonLink = new LinkLabel { Text = "Tải Python từ python.org", Location = new Point(32, 337), AutoSize = true };
        pythonLink.LinkClicked += (s, e) => Browse("https://www.python.org/downloads/windows/");
        var folder = new LinkLabel { Text = "Mở thư mục ứng dụng", Location = new Point(325, 337), AutoSize = true };
        folder.LinkClicked += (s, e) => Process.Start(new ProcessStartInfo(root) { UseShellExecute = true });
        log.Multiline = true; log.ReadOnly = true; log.ScrollBars = ScrollBars.Vertical;
        log.Font = new Font("Consolas", 9); log.SetBounds(32, 377, 584, 160);
        log.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom;
        status.SetBounds(32, 550, 584, 34); status.Anchor = AnchorStyles.Left | AnchorStyles.Right | AnchorStyles.Bottom;
        status.Text = File.Exists(PythonPath) ? "Đã có môi trường. Bấm Mở ứng dụng để bắt đầu." : "Máy mới: chọn tính năng và bấm Cài đặt.";
        Controls.AddRange(new Control[] { title, caption, open, install, semantic, chat, subjects, hint, pythonLink, folder, log, status });
        FormClosing += (s, e) => { if (working) { e.Cancel = true; status.Text = "Đang xử lý. Đợi hoàn tất để đóng cửa sổ."; } };
    }

    string PythonPath { get { return Path.Combine(root, ".venv", "Scripts", "python.exe"); } }
    static void Browse(string url) { Process.Start(new ProcessStartInfo(url) { UseShellExecute = true }); }
    void Append(string message)
    {
        if (!IsDisposed && IsHandleCreated)
            BeginInvoke((Action)(() => log.AppendText(message + Environment.NewLine)));
    }
    void SetWorking(bool value, string message)
    {
        working = value; open.Enabled = install.Enabled = semantic.Enabled = chat.Enabled = subjects.Enabled = !value;
        status.Text = message;
    }

    Task<int> Run(string file, string args)
    {
        return Task.Run(() => {
            var info = new ProcessStartInfo(file, args) { WorkingDirectory = root, UseShellExecute = false,
                CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true,
                StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8 };
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            info.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
            using (var process = new Process { StartInfo = info })
            {
                process.OutputDataReceived += (s, e) => { if (e.Data != null) Append(e.Data); };
                process.ErrorDataReceived += (s, e) => { if (e.Data != null) Append(e.Data); };
                process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine(); process.WaitForExit();
                return process.ExitCode;
            }
        });
    }

    static string FindPython()
    {
        foreach (string command in new[] { "py|-3.12 ", "py|-3.11 ", "py|-3.10 ", "python|", "python3|" })
        {
            string[] parts = command.Split('|');
            try
            {
                var info = new ProcessStartInfo(parts[0], parts[1] + "-c \"import sys; assert (3,10)<=sys.version_info[:2]<=(3,12) and sys.maxsize>2**32; print(sys.executable)\"")
                    { UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
                using (var p = Process.Start(info))
                {
                    if (!p.WaitForExit(5000)) { p.Kill(); continue; }
                    string path = p.StandardOutput.ReadToEnd().Trim();
                    if (p.ExitCode == 0 && File.Exists(path)) return path;
                }
            }
            catch (System.ComponentModel.Win32Exception) { }
        }
        return null;
    }

    async Task OpenApplication()
    {
        if (!File.Exists(PythonPath)) { status.Text = "Chưa cài môi trường. Bấm Cài đặt / sửa môi trường trước."; return; }
        SetWorking(true, "Đang mở LumaNest…");
        try
        {
            int code = await Run(PythonPath, "-u scripts/launch.py --background --no-browser");
            if (code != 0) throw new IOException("Không khởi động được. Xem thông báo ở trên.");
            Browse("http://127.0.0.1:8000/");
            status.Text = "Ứng dụng đã mở. Có thể đóng cửa sổ này; server vẫn chạy trên máy.";
        }
        catch (Exception error) { status.Text = error.Message; Append(error.Message); }
        finally { SetWorking(false, status.Text); }
    }

    async Task InstallApplication()
    {
        SetWorking(true, "Đang chuẩn bị cài đặt…");
        try
        {
            if (!File.Exists(Path.Combine(root, "scripts", "bootstrap.py")))
                throw new IOException("Hãy giải nén toàn bộ gói LumaNest, không chỉ chép riêng file EXE.");
            string python = File.Exists(PythonPath) ? PythonPath : await Task.Run(() => FindPython());
            if (python == null) throw new IOException("Chưa có Python 3.10–3.12 x64. Cài Python từ liên kết bên trên rồi thử lại.");
            string flags = "-u scripts/bootstrap.py";
            if (!semantic.Checked) flags += " --skip-semantic-search";
            if (chat.Checked) flags += " --with-local-chat";
            if (subjects.Checked) flags += " --with-subject-tools";
            status.Text = "Đang cài thư viện và tải model. Tiến độ hiển thị bên dưới.";
            int code = await Run(python, flags);
            if (code != 0) throw new IOException("Cài đặt chưa hoàn tất. Xem lỗi ở trên rồi bấm Cài đặt để thử lại.");
            status.Text = "Cài đặt hoàn tất. Bấm Mở ứng dụng.";
        }
        catch (Exception error) { status.Text = error.Message; Append(error.Message); }
        finally { SetWorking(false, status.Text); }
    }

    [STAThread]
    static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--check")
        {
            string root = AppDomain.CurrentDomain.BaseDirectory;
            bool source = File.Exists(Path.Combine(root, "scripts", "launch.py")) && File.Exists(Path.Combine(root, "scripts", "bootstrap.py"))
                && File.Exists(Path.Combine(root, "fsmart", "app.py"));
            File.WriteAllText(Path.Combine(root, "launcher-check.json"),
                "{\"application\":\"LumaNest\",\"version\":\"1.0.0\",\"source_ready\":" + source.ToString().ToLowerInvariant() + "}");
            return source ? 0 : 1;
        }
        Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new LumaNest()); return 0;
    }
}
