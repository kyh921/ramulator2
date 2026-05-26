#include <vector>

#include "base/base.h"
#include "dram_controller/controller.h"
#include "dram_controller/plugin.h"

namespace Ramulator {

class ActCounterStats final : public IControllerPlugin, public Implementation {
  RAMULATOR_REGISTER_IMPLEMENTATION(IControllerPlugin, ActCounterStats,
                                    "ActCounterStats",
                                    "Counts row opening commands and tracks hot global-bank events.")

 private:
  IDRAMController* m_ctrl = nullptr;
  IDRAM* m_dram = nullptr;

  int m_row_level = -1;
  int m_rank_level = -1;
  int m_bankgroup_level = -1;
  int m_bank_level = -1;

  int m_num_ranks = 0;
  int m_num_bankgroups = 0;
  int m_num_banks_per_group = 0;
  int m_num_global_banks = 0;

  int m_bank_open_threshold = -1;   // -1이면 threshold 기능 비활성

  size_t s_num_opening_cmds = 0;
  size_t s_num_hot_bank_events = 0;

  std::vector<size_t> s_num_opening_cmds_per_gbank;
  std::vector<bool> m_gbank_hot_reported;

 public:
  void init() override {
    if (m_config["bank_open_threshold"]) {
      m_bank_open_threshold = param<int>("bank_open_threshold");
      if (m_bank_open_threshold <= 0) {
        throw InitializationError(
          "bank_open_threshold must be positive when specified."
        );
      }
    }
  }

  void setup(IFrontEnd* frontend, IMemorySystem* memory_system) override {
    m_ctrl = cast_parent<IDRAMController>();
    m_dram = m_ctrl->m_dram;

    m_row_level = m_dram->m_levels("row");
    m_rank_level = m_dram->m_levels("rank");
    m_bankgroup_level = m_dram->m_levels("bankgroup");
    m_bank_level = m_dram->m_levels("bank");

    m_num_ranks = m_dram->get_level_size("rank");
    m_num_bankgroups = m_dram->get_level_size("bankgroup");
    m_num_banks_per_group = m_dram->get_level_size("bank");

    m_num_global_banks = m_num_ranks * m_num_bankgroups * m_num_banks_per_group;

    s_num_opening_cmds_per_gbank.resize(m_num_global_banks, 0);
    m_gbank_hot_reported.resize(m_num_global_banks, false);

    register_stat(s_num_opening_cmds).name("num_opening_cmds");
    register_stat(s_num_hot_bank_events).name("num_hot_bank_events");

    for (int i = 0; i < m_num_global_banks; i++) {
      register_stat(s_num_opening_cmds_per_gbank[i])
        .name("num_opening_cmds_gbank{}", i);
    }
  }

  void update(bool request_found, ReqBuffer::iterator& req_it) override {
    if (!request_found) {
      return;
    }

    bool is_opening = m_dram->m_command_meta(req_it->command).is_opening;
    bool is_row_level =
      (m_dram->m_command_scopes(req_it->command) == m_row_level);

    if (!(is_opening && is_row_level)) {
      return;
    }

    s_num_opening_cmds++;

    int rank_id = req_it->addr_vec[m_rank_level];
    int bankgroup_id = req_it->addr_vec[m_bankgroup_level];
    int bank_id = req_it->addr_vec[m_bank_level];

    int global_bank_id =
        rank_id * (m_num_bankgroups * m_num_banks_per_group)
      + bankgroup_id * m_num_banks_per_group
      + bank_id;

    if (global_bank_id >= 0 && global_bank_id < m_num_global_banks) {
      s_num_opening_cmds_per_gbank[global_bank_id]++;

      if (m_bank_open_threshold > 0) {
        if (!m_gbank_hot_reported[global_bank_id] &&
            s_num_opening_cmds_per_gbank[global_bank_id] >=
              static_cast<size_t>(m_bank_open_threshold)) {
          s_num_hot_bank_events++;
          m_gbank_hot_reported[global_bank_id] = true;
        }
      }
    }
  }
};

}  // namespace Ramulator

// row opening만 셈
/*
#include "base/base.h"
#include "dram_controller/controller.h"
#include "dram_controller/plugin.h"

namespace Ramulator {

class ActCounterStats final : public IControllerPlugin, public Implementation {
  RAMULATOR_REGISTER_IMPLEMENTATION(IControllerPlugin, ActCounterStats,
                                    "ActCounterStats", "Counts row opening commands.")

 private:
  IDRAMController* m_ctrl = nullptr;
  IDRAM* m_dram = nullptr;

  int m_row_level = -1;

  size_t s_num_opening_cmds = 0;

 public:
  void init() override {
    // 지금은 별도 parameter 안 받음
  }

  void setup(IFrontEnd* frontend, IMemorySystem* memory_system) override {
    m_ctrl = cast_parent<IDRAMController>();
    m_dram = m_ctrl->m_dram;

    m_row_level = m_dram->m_levels("row");

    register_stat(s_num_opening_cmds).name("num_opening_cmds");
  }

  void update(bool request_found, ReqBuffer::iterator& req_it) override {
    if (!request_found) {
      return;
    }

    bool is_opening = m_dram->m_command_meta(req_it->command).is_opening;
    bool is_row_level = (m_dram->m_command_scopes(req_it->command) == m_row_level);

    if (is_opening && is_row_level) {
      s_num_opening_cmds++;
    }
  }
};

}  // namespace Ramulator
*/