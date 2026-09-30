#pragma once

#include <atomic>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

class Game;

// A single bounded request is handed to the rendering thread. Pipe I/O stays here.
class AutomationPipe
{
public:
    AutomationPipe();
    ~AutomationPipe();
    void Poll(Game& game);
    std::wstring Name() const;

private:
    struct Request
    {
        explicit Request(std::string value);
        ~Request();
        std::string input, output;
        HANDLE completed;
        bool cancelled = false;
        bool started = false;
    };

    bool Transfer(HANDLE pipe, bool reading, void* buffer, DWORD size, DWORD& transferred);
    void Run();
    HANDLE m_stop;
    std::thread m_thread;
    std::mutex m_mutex;
    std::shared_ptr<Request> m_request;
    std::shared_ptr<Request> m_applying;
    std::atomic<bool> m_available{ false };
};
